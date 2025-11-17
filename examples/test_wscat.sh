#!/bin/bash

# Configuration
WS_ENDPOINT="wss://your-api-id.execute-api.us-east-1.amazonaws.com/prod"
API_KEY="tvZvFpHxVb5WqLUOPfEOd63rWNRanRgF612GwafS"

echo "Testing Published WebSocket API"
echo "Endpoint: $WS_ENDPOINT"
echo ""
echo "Install wscat if not installed:"
echo "  npm install -g wscat"
echo ""
echo "Connect to WebSocket:"
echo "  wscat -c $WS_ENDPOINT"
echo ""
echo "Then send these messages in order:"
echo ""
echo "1. START session:"
echo '{"step":"START","apiKey":"'$API_KEY'"}'
echo ""
echo "2. Send message body:"
echo '{"step":"BODY","index":0,"part":"{\"conversationId\":null,\"message\":{\"role\":\"user\",\"content\":[{\"contentType\":\"text\",\"body\":\"Hello!\"}],\"model\":\"claude-v3.7-sonnet\",\"parentMessageId\":null},\"enableReasoning\":false}"}'
echo ""
echo "3. END session:"
echo '{"step":"END","apiKey":"'$API_KEY'"}'
echo ""
