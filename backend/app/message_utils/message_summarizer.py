"""Message summarization utility for long conversations."""
import logging
import os
from app.bedrock import call_converse_api, compose_args_for_converse_api
from app.repositories.models.conversation import SimpleMessageModel, TextContentModel

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

MAX_MESSAGES_IN_CONTEXT = int(os.environ.get("MAX_MESSAGES_IN_CONTEXT", "20"))


def should_summarize(messages: list[SimpleMessageModel]) -> bool:
    """Check if conversation needs summarization."""
    return len(messages) > MAX_MESSAGES_IN_CONTEXT


def summarize_old_messages(
    messages: list[SimpleMessageModel], model: str = "claude-v3-haiku"
) -> SimpleMessageModel:
    """Summarize old messages to reduce context length."""
    SUMMARY_PROMPT = """Please summarize the conversation above concisely. Focus on:
- Key topics discussed
- Important decisions or conclusions
- Critical context needed for continuing the conversation

Keep the summary under 500 words. Write in the same language as the conversation."""

    messages_to_summarize = messages[:-10]
    
    summary_messages = messages_to_summarize + [
        SimpleMessageModel(
            role="user",
            content=[
                TextContentModel(
                    content_type="text",
                    body=SUMMARY_PROMPT,
                )
            ],
        )
    ]

    try:
        args = compose_args_for_converse_api(
            messages=summary_messages,
            model=model,
            stream=False,
        )
        response = call_converse_api(args)
        
        summary_text = (
            response["output"]["message"]["content"][0]["text"]
            if "message" in response["output"]
            and len(response["output"]["message"]["content"]) > 0
            and "text" in response["output"]["message"]["content"][0]
            else "Previous conversation summary unavailable."
        )

        return SimpleMessageModel(
            role="user",
            content=[
                TextContentModel(
                    content_type="text",
                    body=f"[Previous conversation summary]\n{summary_text}",
                )
            ],
        )
    except Exception as e:
        logger.error(f"Failed to summarize messages: {e}")
        return SimpleMessageModel(
            role="user",
            content=[
                TextContentModel(
                    content_type="text",
                    body="[Previous conversation context truncated due to length]",
                )
            ],
        )


def limit_context_messages(messages: list[SimpleMessageModel]) -> list[SimpleMessageModel]:
    """Limit messages in context, summarizing old ones if needed."""
    if not should_summarize(messages):
        return messages

    logger.info(f"Conversation has {len(messages)} messages. Applying summarization.")
    
    first_message = messages[0] if messages else None
    summary = summarize_old_messages(messages)
    recent_messages = messages[-10:]
    
    result = []
    if first_message and first_message.role in ["system", "instruction"]:
        result.append(first_message)
        result.append(summary)
        result.extend(recent_messages)
    else:
        result.append(summary)
        result.extend(recent_messages)
    
    logger.info(f"Context reduced from {len(messages)} to {len(result)} messages.")
    return result
