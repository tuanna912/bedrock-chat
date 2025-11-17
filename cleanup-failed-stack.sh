#!/bin/bash

BOT_ID="${1:-ask-bot}"
REGION="${2:-us-east-1}"

echo "🗑️  Cleaning up failed stack..."

# Delete failed stack
aws cloudformation delete-stack --stack-name "PublishedWS-$BOT_ID" --region $REGION 2>/dev/null || true

echo "⏳ Waiting for stack deletion..."
aws cloudformation wait stack-delete-complete --stack-name "PublishedWS-$BOT_ID" --region $REGION 2>/dev/null || true

echo "✅ Cleanup complete! You can now redeploy."
