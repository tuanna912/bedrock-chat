#!/bin/bash
set -e

# Fix Git Bash path conversion on Windows
export MSYS_NO_PATHCONV=1

echo "=== Checking Bedrock Chat Deployment Logs ==="

# Configuration
AWS_PROFILE="my-prod"
AWS_REGION="us-east-1"

# Set AWS profile environment variable
export AWS_PROFILE="$AWS_PROFILE"
export AWS_DEFAULT_REGION="$AWS_REGION"

echo ""
echo "Step 1: Finding CodeBuild project..."

# Get CodeBuild project name
PROJECT_NAME=$(aws codebuild list-projects --profile $AWS_PROFILE --region $AWS_REGION --query 'projects[?contains(@, `BedrockChat`) == `true`] | [0]' --output text)

if [ -z "$PROJECT_NAME" ] || [ "$PROJECT_NAME" == "None" ]; then
    echo "Warning: CodeBuild project not found. Searching for any recent builds..."
    PROJECT_NAME=$(aws codebuild list-projects --profile $AWS_PROFILE --region $AWS_REGION --query 'projects[0]' --output text)
fi

echo "CodeBuild Project: $PROJECT_NAME"

# Get latest build ID
echo ""
echo "Step 2: Getting latest build..."
BUILD_ID=$(aws codebuild list-builds-for-project --project-name "$PROJECT_NAME" --profile $AWS_PROFILE --region $AWS_REGION --query 'ids[0]' --output text)

if [ -z "$BUILD_ID" ] || [ "$BUILD_ID" == "None" ]; then
    echo "No builds found for project: $PROJECT_NAME"
    exit 1
fi

echo "Latest Build ID: $BUILD_ID"

# Get build status
echo ""
echo "Step 3: Checking build status..."
BUILD_STATUS=$(aws codebuild batch-get-builds --ids "$BUILD_ID" --profile $AWS_PROFILE --region $AWS_REGION --query 'builds[0].buildStatus' --output text)
echo "Build Status: $BUILD_STATUS"

# Get log group and stream
echo ""
echo "Step 4: Getting build logs information..."
LOG_INFO=$(aws codebuild batch-get-builds --ids "$BUILD_ID" --profile $AWS_PROFILE --region $AWS_REGION --query 'builds[0].logs' --output json)

LOG_GROUP=$(echo $LOG_INFO | jq -r '.groupName')
LOG_STREAM=$(echo $LOG_INFO | jq -r '.streamName')

echo "Log Group: $LOG_GROUP"
echo "Log Stream: $LOG_STREAM"

# List all Lambda functions in the project
echo ""
echo "Step 4.5: Listing all Lambda functions in the project..."
echo "=========================================="
aws lambda list-functions --profile $AWS_PROFILE --region $AWS_REGION --query 'Functions[?contains(FunctionName, `BedrockChat`)].FunctionName' --output table
echo ""

# Tail logs in real-time
echo ""
echo "Step 5: Tailing deployment logs (showing all logs and following new ones)..."
echo "=========================================="
echo ""
echo "Press Ctrl+C to stop watching logs"
echo ""

# Check if user wants to use get-log-events instead of tail
USE_GET_EVENTS=${1:-""}

if [ "$USE_GET_EVENTS" == "--get-events" ]; then
    echo "Using get-log-events to fetch logs..."
    MSYS_NO_PATHCONV=1 aws logs get-log-events \
        --log-group-name "$LOG_GROUP" \
        --log-stream-name "$LOG_STREAM" \
        --profile $AWS_PROFILE \
        --region $AWS_REGION \
        --start-from-head \
        --limit 10000 \
        --query 'events[].message' \
        --output text
else
    # Use aws logs tail to show all logs and follow new ones
    if [ "$BUILD_STATUS" == "IN_PROGRESS" ]; then
        echo "Build is in progress. Watching logs in real-time..."
        MSYS_NO_PATHCONV=1 aws logs tail "$LOG_GROUP" --follow --profile $AWS_PROFILE --region $AWS_REGION
    else
        echo "Build completed with status: $BUILD_STATUS"
        echo "Showing all logs from the build..."
        MSYS_NO_PATHCONV=1 aws logs tail "$LOG_GROUP" --since 2h --profile $AWS_PROFILE --region $AWS_REGION
    fi
fi

echo ""
echo "=========================================="
echo ""
echo "=== Log Check Complete ==="
echo "Build Status: $BUILD_STATUS"
echo ""

if [ "$BUILD_STATUS" == "SUCCEEDED" ]; then
    echo "[SUCCESS] Deployment completed successfully!"
elif [ "$BUILD_STATUS" == "FAILED" ]; then
    echo "[FAILED] Deployment failed. Check the logs above for errors."
fi
