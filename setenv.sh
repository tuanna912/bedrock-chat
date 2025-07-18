#!/bin/bash

# AWS Environment Settings
export REGION=us-east-1
export BEDROCK_REGION=us-east-1
export ENV_NAME=development
export ENV_PREFIX=dev

# AWS Resources
export ACCOUNT=your-account-id
export USER_POOL_ID=your-user-pool-id
export CLIENT_ID=your-client-id

# DynamoDB Tables
export CONVERSATION_TABLE_NAME=BedrockChatStack-DatabaseConversationTable
export BOT_TABLE_NAME=BedrockChatStack-DatabaseBotTable

# S3 Buckets
export DOCUMENT_BUCKET=bedrockchatstack-documentbucket
export LARGE_MESSAGE_BUCKET=bedrockchatstack-largemessagebucket

# OpenSearch Configuration
export OPENSEARCH_DOMAIN_ENDPOINT=https://your-opensearch-domain-endpoint.region.aoss.amazonaws.com

# API Configuration
export PUBLISHED_API_THROTTLE_RATE_LIMIT=100
export PUBLISHED_API_THROTTLE_BURST_LIMIT=50
export PUBLISHED_API_QUOTA_LIMIT=1000
export PUBLISHED_API_QUOTA_PERIOD=DAY
export PUBLISHED_API_DEPLOYMENT_STAGE=api
export PUBLISHED_API_ALLOWED_ORIGINS=*

# Bedrock Configuration
export ENABLE_BEDROCK_CROSS_REGION_INFERENCE=true
export ENABLE_RAG_REPLICAS=false
export ENABLE_BOT_STORE_REPLICAS=false

# CodeBuild
export PUBLISH_API_CODEBUILD_PROJECT_NAME=your-codebuild-project-name

# Local Development
export PORT=8000
export LOG_LEVEL=INFO

echo "Environment variables set successfully!"