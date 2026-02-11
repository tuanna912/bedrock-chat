#!/usr/bin/env node
import "source-map-support/register";
import * as cdk from "aws-cdk-lib";
import { PublishedWebSocketStack } from "../lib/published-websocket-stack";

const app = new cdk.App();

new PublishedWebSocketStack(app, "PublishedWS-ask-bot", {
  env: {
    account: process.env.CDK_DEFAULT_ACCOUNT,
    region: process.env.CDK_DEFAULT_REGION || "us-east-1",
  },
  bedrockRegion: "us-east-1",
  conversationTableName: "BedrockChatStack-DatabaseConversationTableV3C1D85773-FWCQFM9SQJC5	BedrockChatStack-DatabaseConversationTableV3C1D85773-FWCQFM9SQJC5",
  botTableName: "BedrockChatStack-DatabaseBotTableV3201CEEA9-RMBFIP9S7C6R	BedrockChatStack-DatabaseBotTableV3201CEEA9-RMBFIP9S7C6R",
  tableAccessRoleArn: "arn:aws:iam::051255203346:role/BedrockChatStack-DatabaseTableAccessRole59AAC05E-wHp1OHNHokrn",
  largeMessageBucketName: "bedrockchatstack-largemessagebucketad0c9b6b-8u6zpq59113t",
  enableBedrockCrossRegionInference: true,
  enableLambdaSnapStart: false,
  botId: "ask-bot",
  apiKey: "tvZvFpHxVb5WqLUOPfEOd63rWNRanRgF612GwafS",
});
