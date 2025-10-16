#!/bin/bash
set -e

# Fix Git Bash path conversion on Windows
export MSYS_NO_PATHCONV=1

echo "=== Deploying Bedrock Chat to AWS CloudShell ==="

# Configuration
AWS_PROFILE="my-prod"
AWS_REGION="us-east-1"

# Set AWS profile environment variable
export AWS_PROFILE="$AWS_PROFILE"
export AWS_DEFAULT_REGION="$AWS_REGION"

# Deploy command
DEPLOY_CMD='./bin.sh --disable-self-register --allowed-signup-email-domains "seedcomfashion.vn,megazone.com,mz.co.kr" --bedrock-region "us-east-1" --version feature/optimize-memory --cdk-json-override '"'"'{
  "context": {
    "enableSignup": false,
    "enableForgotPassword": false,
    "logoUrl": "/custom-logo.svg"
  }
}'"'"

echo "Step 1: Starting deployment..."
echo "Command: $DEPLOY_CMD"

# Execute deployment
eval "$DEPLOY_CMD"

echo ""
echo "Step 2: Finding CodeBuild project..."

# Get CodeBuild project name
PROJECT_NAME=$(aws codebuild list-projects --profile $AWS_PROFILE --region $AWS_REGION --query 'projects[?contains(@, `BedrockChat`) == `true`] | [0]' --output text)

if [ -z "$PROJECT_NAME" ] || [ "$PROJECT_NAME" == "None" ]; then
    echo "Warning: CodeBuild project not found. Searching for any recent builds..."
    PROJECT_NAME=$(aws codebuild list-projects --profile $AWS_PROFILE --region $AWS_REGION --query 'projects[0]' --output text)
fi

echo "CodeBuild Project: $PROJECT_NAME"

# Get latest build ID
echo ""
echo "Step 3: Getting latest build..."
BUILD_ID=$(aws codebuild list-builds-for-project --project-name "$PROJECT_NAME" --profile $AWS_PROFILE --region $AWS_REGION --query 'ids[0]' --output text)

if [ -z "$BUILD_ID" ] || [ "$BUILD_ID" == "None" ]; then
    echo "No builds found for project: $PROJECT_NAME"
    exit 1
fi

echo "Latest Build ID: $BUILD_ID"

# Get log group and stream
echo ""
echo "Step 4: Getting build logs..."
LOG_INFO=$(aws codebuild batch-get-builds --ids "$BUILD_ID" --profile $AWS_PROFILE --region $AWS_REGION --query 'builds[0].logs' --output json)

LOG_GROUP=$(echo $LOG_INFO | jq -r '.groupName')
LOG_STREAM=$(echo $LOG_INFO | jq -r '.streamName')

echo "Log Group: $LOG_GROUP"
echo "Log Stream: $LOG_STREAM"

# Get logs
echo ""
echo "Step 5: Getting latest logs..."
echo "=========================================="

# Get logs with path conversion disabled
aws logs get-log-events --log-group-name "$LOG_GROUP" --log-stream-name "$LOG_STREAM" --profile $AWS_PROFILE --region $AWS_REGION --limit 100 --query 'events[-50:].message' --output json

echo ""
echo "=== Deployment Complete ==="
echo "To continue monitoring logs, run: ./check-codebuild-logs.sh"