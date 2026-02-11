import json
import logging
import os
from datetime import datetime
from decimal import Decimal as decimal
from queue import SimpleQueue
from threading import Thread

import boto3
from app.repositories.conversation import RecordNotFoundError
from app.routes.schemas.conversation import ChatInput
from app.stream import OnStopInput, OnThinking
from app.usecases.chat import chat
from app.user import User
from boto3.dynamodb.conditions import Key

WEBSOCKET_SESSION_TABLE_NAME = os.environ["WEBSOCKET_SESSION_TABLE_NAME"]
BOT_ID = os.environ.get("BOT_ID", "ask-bot")
API_KEY_PARAMETER_NAME = f"/bedrock-chat/published-bot/{BOT_ID}/api-key"

dynamodb_client = boto3.resource("dynamodb")
table = dynamodb_client.Table(WEBSOCKET_SESSION_TABLE_NAME)
ssm_client = boto3.client("ssm")

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def verify_api_key(api_key: str) -> bool:
    """Verify API key from SSM Parameter Store"""
    try:
        response = ssm_client.get_parameter(
            Name=API_KEY_PARAMETER_NAME, WithDecryption=False
        )
        valid_key = response["Parameter"]["Value"]
        return api_key == valid_key
    except Exception as e:
        logger.error(f"Failed to verify API key: {e}")
        return False


class NotificationSender:
    def __init__(self, endpoint_url: str, connection_id: str) -> None:
        self.commands = SimpleQueue()
        self.endpoint_url = endpoint_url
        self.connection_id = connection_id

    def run(self):
        gatewayapi = boto3.client(
            "apigatewaymanagementapi",
            endpoint_url=self.endpoint_url,
        )

        while True:
            command = self.commands.get()
            if command["type"] == "notify":
                try:
                    gatewayapi.post_to_connection(
                        ConnectionId=self.connection_id,
                        Data=command["payload"],
                    )
                except (
                    gatewayapi.exceptions.GoneException,
                    gatewayapi.exceptions.ForbiddenException,
                ) as e:
                    logger.exception(f"Shutdown notification sender: {e}")
                    break
                except Exception as e:
                    logger.exception(f"Failed to send notification: {e}")
            elif command["type"] == "finish":
                break

    def finish(self):
        self.commands.put({"type": "finish"})

    def notify(self, payload: bytes):
        self.commands.put({"type": "notify", "payload": payload})

    def on_stream(self, token: str):
        payload = json.dumps(dict(status="STREAMING", completion=token)).encode(
            "utf-8"
        )
        self.notify(payload=payload)

    def on_stop(self, arg: OnStopInput):
        payload = json.dumps(
            dict(
                status="STREAMING_END",
                completion="",
                stop_reason=arg["stop_reason"],
                token_count=dict(
                    input=arg["input_token_count"],
                    output=arg["output_token_count"],
                ),
                price=arg["price"],
            )
        ).encode("utf-8")
        self.notify(payload=payload)

    def on_agent_thinking(self, tool_use: OnThinking):
        payload = json.dumps(
            dict(
                status="AGENT_THINKING",
                log={
                    tool_use["tool_use_id"]: {
                        "name": tool_use["name"],
                        "input": tool_use["input"],
                    }
                },
            )
        ).encode("utf-8")
        self.notify(payload=payload)

    def on_agent_tool_result(self, run_result):
        self.notify(
            payload=json.dumps(
                dict(
                    status="AGENT_TOOL_RESULT",
                    result={
                        "toolUseId": run_result["tool_use_id"],
                        "status": run_result["status"],
                    },
                )
            ).encode("utf-8")
        )

    def on_reasoning(self, token: str):
        payload = json.dumps(dict(status="REASONING", completion=token)).encode(
            "utf-8"
        )
        self.notify(payload=payload)


def handler(event, context):
    logger.info(f"Received event: {event}")
    route_key = event["requestContext"]["routeKey"]

    if route_key == "$connect":
        return {"statusCode": 200, "body": "Connected."}
    elif route_key == "$disconnect":
        return {"statusCode": 200, "body": "Disconnected."}

    connection_id = event["requestContext"]["connectionId"]
    domain_name = event["requestContext"]["domainName"]
    stage = event["requestContext"]["stage"]
    endpoint_url = f"https://{domain_name}/{stage}"
    notificator = NotificationSender(
        endpoint_url=endpoint_url,
        connection_id=connection_id,
    )

    now = datetime.now()
    expire = int(now.timestamp()) + 60 * 2
    body = json.loads(event["body"])
    step = body.get("step")
    api_key = body.get("apiKey")

    notification_thread = Thread(target=lambda: notificator.run(), daemon=True)
    notification_thread.start()

    try:
        if step == "START":
            # Verify API key
            if not api_key or not verify_api_key(api_key):
                # Send error via WebSocket
                gatewayapi = boto3.client(
                    "apigatewaymanagementapi", endpoint_url=endpoint_url
                )
                try:
                    gatewayapi.post_to_connection(
                        ConnectionId=connection_id,
                        Data=json.dumps(dict(status="ERROR", reason="Invalid API key.")).encode("utf-8"),
                    )
                except:
                    pass
                return {"statusCode": 403}

            # Store connection
            table.put_item(
                Item={
                    "ConnectionId": connection_id,
                    "MessagePartId": decimal(0),
                    "ApiKeyVerified": True,
                    "expire": expire,
                }
            )
            
            # Send success response via WebSocket
            gatewayapi = boto3.client(
                "apigatewaymanagementapi", endpoint_url=endpoint_url
            )
            try:
                gatewayapi.post_to_connection(
                    ConnectionId=connection_id,
                    Data="Session started.".encode("utf-8"),
                )
            except Exception as e:
                logger.error(f"Failed to send response: {e}")
            
            return {"statusCode": 200}

        elif step == "END":
            # Verify API key again
            if not api_key or not verify_api_key(api_key):
                return {
                    "statusCode": 403,
                    "body": json.dumps(
                        dict(status="ERROR", reason="Invalid API key.")
                    ),
                }

            # Create user with bot_id
            user = User(
                id=f"published#{BOT_ID}",
                name="Published User",
                email="published@bot.local",
                groups=[]
            )

            # Retrieve and concatenate message parts
            response = table.query(
                KeyConditionExpression=Key("ConnectionId").eq(connection_id)
                & Key("MessagePartId").gte(1)
            )
            message_parts = sorted(response["Items"], key=lambda x: x["MessagePartId"])
            full_message = "".join(item["MessagePart"] for item in message_parts)

            # Process chat
            message_data = json.loads(full_message)
            
            # Convert camelCase to snake_case for backend compatibility
            if "conversationId" in message_data:
                message_data["conversation_id"] = message_data.pop("conversationId")
            if "botId" in message_data:
                message_data["bot_id"] = message_data.pop("botId")
            if "enableReasoning" in message_data:
                message_data["enable_reasoning"] = message_data.pop("enableReasoning")
            
            # Convert message fields
            if "message" in message_data:
                msg = message_data["message"]
                if "parentMessageId" in msg:
                    msg["parent_message_id"] = msg.pop("parentMessageId")
                if "messageId" in msg:
                    msg["message_id"] = msg.pop("messageId")
                if "usedChunks" in msg:
                    msg.pop("usedChunks")  # Remove unused fields
                if "thinkingLog" in msg:
                    msg.pop("thinkingLog")
                if "feedback" in msg:
                    msg.pop("feedback")
                
                # Convert content fields
                if "content" in msg:
                    for content in msg["content"]:
                        if "contentType" in content:
                            content["content_type"] = content.pop("contentType")
            
            if message_data.get("conversation_id") is None:
                from ulid import ULID
                message_data["conversation_id"] = str(ULID())
            
            chat_input = ChatInput(**message_data)
            if "bot_id" not in message_data:
                chat_input.bot_id = BOT_ID

            try:
                conversation, message = chat(
                    user=user,
                    chat_input=chat_input,
                    on_stream=lambda token: notificator.on_stream(token=token),
                    on_stop=lambda arg: notificator.on_stop(arg=arg),
                    on_thinking=lambda tool_use: notificator.on_agent_thinking(
                        tool_use=tool_use
                    ),
                    on_tool_result=lambda run_result: notificator.on_agent_tool_result(
                        run_result=run_result
                    ),
                    on_reasoning=lambda token: notificator.on_reasoning(token=token),
                )
                # Send conversation metadata before finishing
                import time
                notificator.notify(
                    payload=json.dumps(
                        dict(
                            status="CONVERSATION_METADATA",
                            conversation_id=conversation.id,
                            message_id=conversation.last_message_id,
                        )
                    ).encode("utf-8")
                )
                time.sleep(0.5)  # Give time for the message to be sent
                return {"statusCode": 200, "body": "Message sent."}
            except RecordNotFoundError:
                return {
                    "statusCode": 404,
                    "body": json.dumps(
                        dict(status="ERROR", reason=f"Bot {BOT_ID} not found.")
                    ),
                }
            except Exception as e:
                logger.exception(f"Failed to process chat: {e}")
                return {
                    "statusCode": 500,
                    "body": json.dumps(
                        dict(status="ERROR", reason=f"Failed to process: {e}")
                    ),
                }
        else:
            # Store message part
            part_index = body["index"] + 1
            message_part = body["part"]
            table.put_item(
                Item={
                    "ConnectionId": connection_id,
                    "MessagePartId": decimal(part_index),
                    "MessagePart": message_part,
                    "expire": expire,
                }
            )
            # Send ack via WebSocket
            gatewayapi = boto3.client(
                "apigatewaymanagementapi", endpoint_url=endpoint_url
            )
            try:
                gatewayapi.post_to_connection(
                    ConnectionId=connection_id,
                    Data="Message part received.".encode("utf-8"),
                )
            except Exception as e:
                logger.error(f"Failed to send ack: {e}")
            
            return {"statusCode": 200}

    except Exception as e:
        logger.exception(f"Operation failed: {e}")
        return {
            "statusCode": 500,
            "body": json.dumps({"status": "ERROR", "reason": str(e)}),
        }
    finally:
        import time
        time.sleep(0.2)  # Ensure all messages are sent
        notificator.finish()
        notification_thread.join(timeout=60)
