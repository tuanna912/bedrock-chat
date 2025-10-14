"""
CloudWatch Logging Setup for Production Deployment

This module configures logging to send logs to AWS CloudWatch automatically
when the application is deployed. It works for:
- AWS Lambda (auto-configured)
- ECS/Fargate (auto-configured with awslogs driver)
- EC2/VPS (requires watchtower)
"""

import logging
import os
import sys
from typing import Optional

# Environment variables
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
ENABLE_CLOUDWATCH = os.environ.get("ENABLE_CLOUDWATCH", "true").lower() == "true"
CLOUDWATCH_LOG_GROUP = os.environ.get(
    "CLOUDWATCH_LOG_GROUP", "/aws/bedrock-chat/backend"
)
AWS_REGION = os.environ.get("AWS_REGION", os.environ.get("BEDROCK_REGION", "us-east-1"))

# Detect environment
IS_LAMBDA = os.environ.get("AWS_EXECUTION_ENV") is not None
IS_ECS = os.environ.get("ECS_CONTAINER_METADATA_URI") is not None

# Try to import watchtower for CloudWatch logging
WATCHTOWER_AVAILABLE = False
if not IS_LAMBDA and not IS_ECS:  # Only need watchtower for non-Lambda/ECS
    try:
        import watchtower
        WATCHTOWER_AVAILABLE = True
    except ImportError:
        pass


def setup_logging() -> logging.Logger:
    """
    Setup application logging with CloudWatch integration
    
    Returns:
        Configured root logger
    """
    # Get root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, LOG_LEVEL.upper()))
    
    # Remove existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # Console handler (always enabled)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(getattr(logging, LOG_LEVEL.upper()))
    
    # Format
    formatter = logging.Formatter(
        fmt='%(asctime)s [%(levelname)s] %(name)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)
    
    # CloudWatch setup based on environment
    if ENABLE_CLOUDWATCH:
        if IS_LAMBDA:
            # Lambda automatically sends logs to CloudWatch
            # No additional configuration needed
            root_logger.info(f"[LOGGING] Running on Lambda - logs auto-sent to CloudWatch")
            root_logger.info(f"[LOGGING] Log level: {LOG_LEVEL}")
            
        elif IS_ECS:
            # ECS/Fargate with awslogs driver automatically sends to CloudWatch
            root_logger.info(f"[LOGGING] Running on ECS/Fargate - logs auto-sent to CloudWatch")
            root_logger.info(f"[LOGGING] Log level: {LOG_LEVEL}")
            
        elif WATCHTOWER_AVAILABLE:
            # EC2 or other environments - use watchtower
            try:
                cloudwatch_handler = watchtower.CloudWatchLogHandler(
                    log_group=CLOUDWATCH_LOG_GROUP,
                    stream_name=f"{os.environ.get('HOSTNAME', 'unknown')}-{os.getpid()}",
                    use_queues=True,
                    send_interval=10,
                    create_log_group=True,
                    boto3_session=None,  # Uses default credentials
                )
                cloudwatch_handler.setLevel(getattr(logging, LOG_LEVEL.upper()))
                cloudwatch_handler.setFormatter(formatter)
                root_logger.addHandler(cloudwatch_handler)
                
                root_logger.info(f"[LOGGING] CloudWatch handler added successfully")
                root_logger.info(f"[LOGGING] Log group: {CLOUDWATCH_LOG_GROUP}")
                root_logger.info(f"[LOGGING] AWS Region: {AWS_REGION}")
                
            except Exception as e:
                root_logger.warning(f"[LOGGING] Failed to setup CloudWatch handler: {e}")
                root_logger.warning(f"[LOGGING] Continuing with console logging only")
        else:
            root_logger.warning(f"[LOGGING] CloudWatch enabled but watchtower not available")
            root_logger.warning(f"[LOGGING] Install with: pip install watchtower")
            root_logger.warning(f"[LOGGING] Continuing with console logging only")
    else:
        root_logger.info(f"[LOGGING] CloudWatch disabled - console logging only")
        root_logger.info(f"[LOGGING] Log level: {LOG_LEVEL}")
    
    # Log environment info
    root_logger.info(f"[LOGGING] Environment: Lambda={IS_LAMBDA}, ECS={IS_ECS}")
    root_logger.info(f"[LOGGING] Watchtower available: {WATCHTOWER_AVAILABLE}")
    
    return root_logger


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance with the given name
    
    Args:
        name: Logger name (usually __name__)
        
    Returns:
        Logger instance
    """
    return logging.getLogger(name)


# Initialize logging on module import
_initialized = False

def initialize_logging():
    """Initialize logging (called once at startup)"""
    global _initialized
    if not _initialized:
        setup_logging()
        _initialized = True
        logger = logging.getLogger(__name__)
        logger.info("[LOGGING] ========== Logging Initialized ==========")
        logger.info(f"[LOGGING] Memory compression logs will be sent to CloudWatch")
