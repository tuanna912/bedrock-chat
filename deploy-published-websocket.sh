#!/bin/bash
set -e

echo "🚀 Deploying Published WebSocket Stack via CodeBuild..."
echo ""

# Parameters
BOT_ID="${1:-ask-bot}"
API_KEY="${2:-tvZvFpHxVb5WqLUOPfEOd63rWNRanRgF612GwafS}"
REGION="${3:-us-east-1}"
REPO_URL="${4:-https://github.com/tuanna912/bedrock-chat.git}"
VERSION="${5:-feature/no-authen-chatbot}"

echo "📋 Configuration:"
echo "   Bot ID: $BOT_ID"
echo "   API Key: ${API_KEY:0:20}..."
echo "   Region: $REGION"
echo "   Repo: $REPO_URL"
echo "   Version: $VERSION"
echo ""

# Validate BedrockChatStack exists
echo "🔍 Checking BedrockChatStack..."
if ! aws cloudformation describe-stacks --stack-name BedrockChatStack --region $REGION >/dev/null 2>&1; then
    echo "❌ ERROR: BedrockChatStack not found!"
    echo "   Please deploy the main Bedrock Chat stack first using:"
    echo "   ./bin.sh"
    exit 1
fi
echo "   ✓ BedrockChatStack found"
echo ""

# Step 1: Create SSM Parameter
echo "✅ Step 1: Creating SSM Parameter..."
aws ssm put-parameter \
  --name "/bedrock-chat/published-bot/$BOT_ID/api-key" \
  --value "$API_KEY" \
  --type "String" \
  --description "API key for published bot $BOT_ID" \
  --region $REGION \
  --overwrite 2>/dev/null || echo "   Parameter already exists, skipping..."

# Step 2: Create CloudFormation template for CodeBuild
echo ""
echo "✅ Step 2: Creating CodeBuild project..."

cat > /tmp/deploy-published-ws.yml <<EOF
AWSTemplateFormatVersion: "2010-09-09"
Description: Deploy Published WebSocket Stack via CodeBuild

Parameters:
  BotId:
    Type: String
    Default: "$BOT_ID"
  ApiKey:
    Type: String
    Default: "$API_KEY"
    NoEcho: true
  RepoUrl:
    Type: String
    Default: "$REPO_URL"
  Version:
    Type: String
    Default: "$VERSION"

Resources:
  ProjectRole:
    Type: AWS::IAM::Role
    Properties:
      AssumeRolePolicyDocument:
        Statement:
          - Action: sts:AssumeRole
            Effect: Allow
            Principal:
              Service: codebuild.amazonaws.com
      ManagedPolicyArns:
        - !Sub "arn:\${AWS::Partition}:iam::aws:policy/AdministratorAccess"

  ProjectRolePolicy:
    Type: AWS::IAM::Policy
    Properties:
      PolicyDocument:
        Statement:
          - Action:
              - logs:CreateLogGroup
              - logs:CreateLogStream
              - logs:PutLogEvents
            Effect: Allow
            Resource: !Sub "arn:\${AWS::Partition}:logs:\${AWS::Region}:\${AWS::AccountId}:log-group:/aws/codebuild/*"
          - Action:
              - codebuild:*
            Effect: Allow
            Resource: "*"
      PolicyName: ProjectRolePolicy
      Roles:
        - !Ref ProjectRole

  Project:
    Type: AWS::CodeBuild::Project
    Properties:
      Artifacts:
        Type: NO_ARTIFACTS
      Environment:
        ComputeType: BUILD_GENERAL1_SMALL
        Image: aws/codebuild/standard:7.0
        ImagePullCredentialsType: CODEBUILD
        PrivilegedMode: true
        Type: LINUX_CONTAINER
        EnvironmentVariables:
          - Name: BOT_ID
            Value: !Ref BotId
          - Name: API_KEY
            Value: !Ref ApiKey
          - Name: REPO_URL
            Value: !Ref RepoUrl
          - Name: VERSION
            Value: !Ref Version
      ServiceRole: !GetAtt ProjectRole.Arn
      Source:
        BuildSpec: |
          version: 0.2
          env:
            exported-variables:
              - CONVERSATION_TABLE
              - BOT_TABLE
              - TABLE_ACCESS_ROLE
              - LARGE_MESSAGE_BUCKET
          phases:
            install:
              runtime-versions:
                nodejs: 22
            build:
              commands:
                - echo "Cloning repository..."
                - git clone --branch \$VERSION \$REPO_URL bedrock-chat
                - cd bedrock-chat/cdk
                - echo "Installing dependencies..."
                - npm ci
                - echo "Bootstrapping CDK..."
                - npx cdk bootstrap
                - echo "Getting BedrockChatStack outputs..."
                - export CONVERSATION_TABLE=\$(aws cloudformation describe-stacks --stack-name BedrockChatStack --query 'Stacks[0].Outputs[?OutputKey==\`ConversationTableNameV3\`].OutputValue' --output text)
                - export BOT_TABLE=\$(aws cloudformation describe-stacks --stack-name BedrockChatStack --query 'Stacks[0].Outputs[?OutputKey==\`BotTableNameV3\`].OutputValue' --output text)
                - export TABLE_ACCESS_ROLE=\$(aws cloudformation describe-stacks --stack-name BedrockChatStack --query 'Stacks[0].Outputs[?OutputKey==\`TableAccessRoleArn\`].OutputValue' --output text)
                - export LARGE_MESSAGE_BUCKET=\$(aws cloudformation describe-stacks --stack-name BedrockChatStack --query 'Stacks[0].Outputs[?OutputKey==\`LargeMessageBucketName\`].OutputValue' --output text)
                - echo "Conversation Table - \$CONVERSATION_TABLE"
                - echo "Bot Table - \$BOT_TABLE"
                - echo "Table Access Role - \$TABLE_ACCESS_ROLE"
                - echo "Large Message Bucket - \$LARGE_MESSAGE_BUCKET"
                - test -n "\$CONVERSATION_TABLE" || (echo "ERROR - Missing CONVERSATION_TABLE" && exit 1)
                - test -n "\$BOT_TABLE" || (echo "ERROR - Missing BOT_TABLE" && exit 1)
                - test -n "\$TABLE_ACCESS_ROLE" || (echo "ERROR - Missing TABLE_ACCESS_ROLE" && exit 1)
                - test -n "\$LARGE_MESSAGE_BUCKET" || (echo "ERROR - Missing LARGE_MESSAGE_BUCKET" && exit 1)
                - echo "Deploying Published WebSocket Stack..."
                - |
                  cat > bin/deploy-published-ws.ts <<'EOTS'
                  #!/usr/bin/env node
                  import "source-map-support/register";
                  import * as cdk from "aws-cdk-lib";
                  import { PublishedWebSocketStack } from "../lib/published-websocket-stack";
                  
                  const app = new cdk.App();
                  const botId = process.env.BOT_ID || "ask-bot";
                  const apiKey = process.env.API_KEY || "";
                  
                  new PublishedWebSocketStack(app, \`PublishedWS-\${botId}\`, {
                    env: {
                      account: process.env.CDK_DEFAULT_ACCOUNT,
                      region: process.env.CDK_DEFAULT_REGION,
                    },
                    bedrockRegion: "us-east-1",
                    conversationTableName: process.env.CONVERSATION_TABLE || "",
                    botTableName: process.env.BOT_TABLE || "",
                    tableAccessRoleArn: process.env.TABLE_ACCESS_ROLE || "",
                    largeMessageBucketName: process.env.LARGE_MESSAGE_BUCKET || "",
                    enableBedrockCrossRegionInference: true,
                    enableLambdaSnapStart: false,
                    botId,
                    apiKey,
                  });
                  EOTS
                - npx cdk deploy --app "npx ts-node bin/deploy-published-ws.ts" --require-approval never
        Type: NO_SOURCE

Outputs:
  ProjectName:
    Value: !Ref Project
EOF

# Step 3: Deploy CloudFormation stack
echo ""
echo "✅ Step 3: Deploying CloudFormation stack..."
STACK_NAME="PublishedWSCodeBuild-$BOT_ID"

aws cloudformation deploy \
  --stack-name $STACK_NAME \
  --template-file /tmp/deploy-published-ws.yml \
  --capabilities CAPABILITY_IAM \
  --parameter-overrides \
    BotId=$BOT_ID \
    ApiKey=$API_KEY \
    RepoUrl=$REPO_URL \
    Version=$VERSION \
  --region $REGION

# Step 4: Get project name and start build
echo ""
echo "✅ Step 4: Starting CodeBuild..."
PROJECT_NAME=$(aws cloudformation describe-stacks \
  --stack-name $STACK_NAME \
  --query 'Stacks[0].Outputs[?OutputKey==`ProjectName`].OutputValue' \
  --output text \
  --region $REGION)

BUILD_ID=$(aws codebuild start-build \
  --project-name $PROJECT_NAME \
  --region $REGION \
  --query 'build.id' \
  --output text)

echo "   Build ID: $BUILD_ID"
echo ""
echo "⏳ Waiting for build to complete..."

# Step 5: Wait for build
while true; do
  BUILD_STATUS=$(aws codebuild batch-get-builds \
    --ids $BUILD_ID \
    --region $REGION \
    --query 'builds[0].buildStatus' \
    --output text)
  
  if [[ "$BUILD_STATUS" == "SUCCEEDED" ]]; then
    echo ""
    echo "✅ Build completed successfully!"
    break
  elif [[ "$BUILD_STATUS" == "FAILED" || "$BUILD_STATUS" == "STOPPED" ]]; then
    echo ""
    echo "❌ Build failed with status: $BUILD_STATUS"
    exit 1
  fi
  
  printf "."
  sleep 10
done

# Step 6: Get WebSocket endpoint
echo ""
echo "✅ Step 6: Getting WebSocket endpoint..."
WS_ENDPOINT=$(aws cloudformation describe-stacks \
  --stack-name "PublishedWS-$BOT_ID" \
  --query 'Stacks[0].Outputs[?OutputKey==`WebSocketEndpoint`].OutputValue' \
  --output text \
  --region $REGION)

echo ""
echo "🎉 Deployment completed!"
echo ""
echo "📋 Connection Details:"
echo "   WebSocket Endpoint: $WS_ENDPOINT"
echo "   API Key: $API_KEY"
echo ""
echo "🧪 Test with:"
echo "   open examples/published-websocket-client.html"
echo ""
