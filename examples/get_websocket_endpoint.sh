#!/bin/bash

# Get WebSocket endpoint from CloudFormation stack
STACK_NAME="PublishedWS-ask-bot"
PROFILE="infra_deploy"
REGION="us-east-1"

echo "Fetching WebSocket endpoint from stack: $STACK_NAME"
echo ""

WS_ENDPOINT=$(aws cloudformation describe-stacks \
  --profile $PROFILE \
  --region $REGION \
  --stack-name $STACK_NAME \
  --query 'Stacks[0].Outputs[?OutputKey==`WebSocketEndpoint`].OutputValue' \
  --output text)

if [ -z "$WS_ENDPOINT" ]; then
  echo "❌ Stack not found or no WebSocketEndpoint output"
  exit 1
fi

echo "✅ WebSocket Endpoint: $WS_ENDPOINT"
echo ""
echo "API Key (from SSM): tvZvFpHxVb5WqLUOPfEOd63rWNRanRgF612GwafS"
echo ""
echo "Test with HTML client:"
echo "  open examples/published-websocket-client.html"
echo ""
echo "Or test with Python:"
echo "  python3 examples/test_published_websocket.py"
