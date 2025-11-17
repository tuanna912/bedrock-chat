#!/usr/bin/env node
import "source-map-support/register";
import * as cdk from "aws-cdk-lib";
import { PublishedWebSocketStack } from "../lib/published-websocket-stack";

const app = new cdk.App();

// Test stack với mock values
new PublishedWebSocketStack(app, "TestPublishedWS", {
  env: {
    account: process.env.CDK_DEFAULT_ACCOUNT,
    region: process.env.CDK_DEFAULT_REGION || "us-east-1",
  },
  bedrockRegion: "us-east-1",
  conversationTableName: "test-conversation-table",
  botTableName: "test-bot-table",
  tableAccessRoleArn: "arn:aws:iam::123456789012:role/test-role",
  largeMessageBucketName: "test-bucket",
  enableBedrockCrossRegionInference: true,
  enableLambdaSnapStart: false,
  botId: "ask-bot",
  apiKey: "tvZvFpHxVb5WqLUOPfEOd63rWNRanRgF612GwafS",
});
