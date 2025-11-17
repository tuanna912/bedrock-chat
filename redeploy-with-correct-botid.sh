#!/bin/bash
set -e

CORRECT_BOT_ID="01K9Y36WF9KQH1WFKH0GTVTQW6"
API_KEY="tvZvFpHxVb5WqLUOPfEOd63rWNRanRgF612GwafS"
REGION="us-east-1"
PROFILE="infra_deploy"

echo "🔄 Redeploying with correct Bot ID..."
echo "Bot ID: $CORRECT_BOT_ID"
echo ""

# Step 1: Delete old stacks
echo "✅ Step 1: Cleaning up old stacks..."
aws cloudformation delete-stack --profile $PROFILE --stack-name PublishedWS-ask-bot --region $REGION 2>/dev/null || true
aws cloudformation delete-stack --profile $PROFILE --stack-name PublishedWSCodeBuild-ask-bot --region $REGION 2>/dev/null || true

echo "⏳ Waiting for deletion..."
sleep 10

# Step 2: Delete old SSM parameter
echo ""
echo "✅ Step 2: Deleting old SSM parameter..."
aws ssm delete-parameter --profile $PROFILE --name "/bedrock-chat/published-bot/ask-bot/api-key" --region $REGION 2>/dev/null || true

# Step 3: Create new SSM parameter with correct bot ID
echo ""
echo "✅ Step 3: Creating SSM parameter with correct Bot ID..."
aws ssm put-parameter \
  --profile $PROFILE \
  --name "/bedrock-chat/published-bot/$CORRECT_BOT_ID/api-key" \
  --value "$API_KEY" \
  --type "String" \
  --description "API key for published bot $CORRECT_BOT_ID" \
  --region $REGION \
  --overwrite

# Step 4: Deploy with correct bot ID
echo ""
echo "✅ Step 4: Deploying Published WebSocket Stack..."
echo "Run this command:"
echo ""
echo "./deploy-published-websocket.sh $CORRECT_BOT_ID $API_KEY $REGION"
echo ""
