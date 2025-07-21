import json
import logging
import os
from typing import Literal

import boto3
from app.repositories.common import compose_sk, decompose_sk, get_bot_table_client
from app.routes.schemas.bot import type_sync_status
from reretry import retry

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource("dynamodb")

RETRIES_TO_UPDATE_SYNC_STATUS = 4
RETRY_DELAY_TO_UPDATE_SYNC_STATUS = 2

# Mapping lỗi để hiển thị thông báo dễ hiểu hơn
ERROR_MESSAGES = {
    "INGESTION_TIMEOUT": "Knowledge base creation timed out. Please try again or contact support if the issue persists.",
    "INGESTION_STOPPED": "Knowledge base creation was stopped unexpectedly.",
    "KNOWLEDGE_BASE_CREATION_FAILED": "Failed to create knowledge base. Please check your configuration and try again.",
    "VALIDATION_ERROR": "Invalid configuration detected. Please check your bot settings.",
    "PERMISSION_ERROR": "Insufficient permissions to create knowledge base. Please contact your administrator.",
    "RESOURCE_LIMIT_EXCEEDED": "Resource limits exceeded. Please try again later or contact support.",
    "MODEL_NOT_AVAILABLE": "The selected embedding model is not available in this region.",
    "CONFLICT_EXCEPTION": "Too many concurrent knowledge base operations. Please wait a moment and try again.",
    "ConflictException": "Another knowledge base operation is currently in progress. Please wait for it to complete and try again.",
    "DEFAULT": "An unexpected error occurred during bot creation. Please try again."
}

@retry(tries=RETRIES_TO_UPDATE_SYNC_STATUS, delay=RETRY_DELAY_TO_UPDATE_SYNC_STATUS)
def update_sync_status(
    user_id: str,
    bot_id: str,
    sync_status: type_sync_status,
    sync_status_reason: str,
    last_exec_id: str,
):
    logger.info(f"Updating sync status for bot {bot_id}: {sync_status} - {sync_status_reason}")
    table = get_bot_table_client()
    table.update_item(
        Key={"PK": user_id, "SK": compose_sk(bot_id, "bot")},
        UpdateExpression="SET SyncStatus = :sync_status, SyncStatusReason = :sync_status_reason, LastExecId = :last_exec_id",
        ExpressionAttributeValues={
            ":sync_status": sync_status,
            ":sync_status_reason": sync_status_reason,
            ":last_exec_id": last_exec_id,
        },
    )
    logger.info(f"Successfully updated sync status for bot {bot_id}")


def extract_from_cause(cause_str: str) -> tuple:
    logger.debug(f"Extracting PK and SK from cause: {cause_str}")
    cause = json.loads(cause_str)
    logger.debug(f"Cause: {cause}")
    environment_variables = cause["Build"]["Environment"]["EnvironmentVariables"]
    logger.debug(f"Environment variables: {environment_variables}")

    pk = next(
        (item["Value"] for item in environment_variables if item["Name"] == "PK"), None
    )
    sk = next(
        (item["Value"] for item in environment_variables if item["Name"] == "SK"), None
    )

    if not pk or not sk:
        raise ValueError("PK or SK not found in cause.")

    build_arn = cause["Build"].get("Arn", "")

    logger.debug(f"PK: {pk}, SK: {sk}, Build ARN: {build_arn}")

    return pk, sk, build_arn


def get_user_friendly_error_message(sync_status_reason: str, error_details: str = "") -> str:
    """Trả về thông báo lỗi dễ hiểu cho người dùng"""

    # Kiểm tra các từ khóa trong sync_status_reason để xác định loại lỗi
    reason_lower = sync_status_reason.lower()

    if "timeout" in reason_lower:
        return ERROR_MESSAGES["INGESTION_TIMEOUT"]
    elif "stopped" in reason_lower:
        return ERROR_MESSAGES["INGESTION_STOPPED"]
    elif "validation" in reason_lower or "invalid" in reason_lower:
        return ERROR_MESSAGES["VALIDATION_ERROR"]
    elif "permission" in reason_lower or "access" in reason_lower:
        return ERROR_MESSAGES["PERMISSION_ERROR"]
    elif "limit" in reason_lower or "quota" in reason_lower:
        return ERROR_MESSAGES["RESOURCE_LIMIT_EXCEEDED"]
    elif "model" in reason_lower and ("not available" in reason_lower or "invalid" in reason_lower):
        return ERROR_MESSAGES["MODEL_NOT_AVAILABLE"]
    elif "conflictexception" in reason_lower or "concurrent ingestion" in reason_lower:
        return ERROR_MESSAGES["ConflictException"]
    elif "conflict" in reason_lower and "ingestion" in reason_lower:
        return ERROR_MESSAGES["ConflictException"]
    elif "knowledge base" in reason_lower and "failed" in reason_lower:
        return ERROR_MESSAGES["KNOWLEDGE_BASE_CREATION_FAILED"]
    else:
        return ERROR_MESSAGES["DEFAULT"]


def handler(event, context):
    logger.info(f"Event: {event}")
    try:
        cause = event.get("cause", None)
        ingestion_job = event.get("ingestion_job", None)

        # Initialize variables
        pk: str
        sk: str
        sync_status: type_sync_status
        sync_status_reason: str
        last_exec_id: str

        if cause:
            # UpdateSyncStatusFailed
            logger.error(f"Step Function failed with cause: {cause}")
            pk, sk, build_arn = extract_from_cause(cause)
            sync_status = "FAILED"
            sync_status_reason = get_user_friendly_error_message(cause, cause)
            last_exec_id = build_arn
        elif ingestion_job:
            # UpdateSyncStatusFailedForIngestion
            logger.error(f"Ingestion job failed: {ingestion_job}")
            pk = event["pk"]
            sk = event["sk"]
            sync_status = "FAILED"
            failure_reasons = str(ingestion_job["ingestionJob"]["failureReasons"])
            sync_status_reason = get_user_friendly_error_message(failure_reasons, failure_reasons)
            last_exec_id = ingestion_job["ingestionJob"]["ingestionJobId"]
        else:
            # Normal status update
            pk = event["pk"]
            sk = event["sk"]
            sync_status = event["sync_status"]
            raw_reason = event.get("sync_status_reason", "")
            # Chỉ làm đẹp thông báo lỗi nếu sync_status là FAILED
            if sync_status == "FAILED":
                sync_status_reason = get_user_friendly_error_message(raw_reason, raw_reason)
            else:
                sync_status_reason = raw_reason
            last_exec_id = event.get("last_exec_id", "")

        user_id = pk
        bot_id = decompose_sk(sk)

        logger.info(
            f"Updating sync status for bot {bot_id} of user {user_id} to {sync_status} with reason: {sync_status_reason}"
        )

        update_sync_status(
            user_id, bot_id, sync_status, sync_status_reason, last_exec_id
        )

        return {
            "statusCode": 200,
            "body": json.dumps({
                "message": "Sync status updated successfully.",
                "bot_id": bot_id,
                "sync_status": sync_status,
                "sync_status_reason": sync_status_reason
            }),
        }
    except Exception as e:
        logger.error(f"Error updating sync status: {e}")
        logger.error(f"Event that caused error: {event}")
        # Cố gắng extract bot_id để log
        try:
            if "pk" in event and "sk" in event:
                bot_id = decompose_sk(event["sk"])
                logger.error(f"Failed to update sync status for bot {bot_id}")
        except:
            pass

        return {
            "statusCode": 500,
            "body": json.dumps({
                "error": "Error updating sync status.",
                "details": str(e)
            })
        }
