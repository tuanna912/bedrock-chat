#!/bin/bash
set -e

# Fix Git Bash path conversion on Windows
export MSYS_NO_PATHCONV=1

echo "=== Watching Bedrock Chat Lambda Function Logs ==="

# Configuration
AWS_PROFILE="my-prod"
AWS_REGION="us-east-1"

# Set AWS profile environment variable
export AWS_PROFILE="$AWS_PROFILE"
export AWS_DEFAULT_REGION="$AWS_REGION"

echo ""
echo "Step 1: Finding all Lambda functions in the project..."
echo "=========================================="

# Get all Lambda function names containing BedrockChat
FUNCTION_NAMES=$(aws lambda list-functions --profile $AWS_PROFILE --region $AWS_REGION --query 'Functions[?contains(FunctionName, `BedrockChat`)].FunctionName' --output text)

if [ -z "$FUNCTION_NAMES" ]; then
    echo "No Lambda functions found with 'BedrockChat' in the name."
    exit 1
fi

echo "Found Lambda functions:"
echo "$FUNCTION_NAMES" | tr '\t' '\n' | nl
echo ""

# Find the main API handler (BackendApiHandler) and WebSocket handler
API_HANDLER=$(echo "$FUNCTION_NAMES" | tr '\t' '\n' | grep "BackendApiHandler" | head -1)
WEBSOCKET_HANDLER=$(echo "$FUNCTION_NAMES" | tr '\t' '\n' | grep "WebSocketHandler" | head -1)

echo "Step 2: Select which Lambda function to watch:"
echo "=========================================="
echo ""
echo "Main functions:"
echo "  1) $API_HANDLER (API/Chat Handler)"
echo "  2) $WEBSOCKET_HANDLER (WebSocket Handler)"
echo "  3) All functions (may not work on some AWS CLI versions)"
echo ""
read -p "Enter your choice (1-3, or press Enter for option 1): " choice
choice=${choice:-1}

echo ""
echo "Step 3: Watching logs in real-time..."
echo "=========================================="
echo ""
echo "Press Ctrl+C to stop watching logs"
echo ""

case $choice in
    1)
        echo "Watching: $API_HANDLER"
        echo ""
        MSYS_NO_PATHCONV=1 aws logs tail "/aws/lambda/$API_HANDLER" --follow --format short --profile $AWS_PROFILE --region $AWS_REGION
        ;;
    2)
        echo "Watching: $WEBSOCKET_HANDLER"
        echo ""
        MSYS_NO_PATHCONV=1 aws logs tail "/aws/lambda/$WEBSOCKET_HANDLER" --follow --format short --profile $AWS_PROFILE --region $AWS_REGION
        ;;
    3)
        echo "Watching all functions:"
        for func in $FUNCTION_NAMES; do
            echo "  - $func"
        done
        echo ""
        # Build log group names as separate arguments
        LOG_GROUPS_ARRAY=()
        for func in $FUNCTION_NAMES; do
            LOG_GROUPS_ARRAY+=("/aws/lambda/$func")
        done
        MSYS_NO_PATHCONV=1 aws logs tail "${LOG_GROUPS_ARRAY[@]}" --follow --format short --profile $AWS_PROFILE --region $AWS_REGION
        ;;
    *)
        echo "Invalid choice. Watching API Handler by default."
        echo ""
        MSYS_NO_PATHCONV=1 aws logs tail "/aws/lambda/$API_HANDLER" --follow --format short --profile $AWS_PROFILE --region $AWS_REGION
        ;;
esac
