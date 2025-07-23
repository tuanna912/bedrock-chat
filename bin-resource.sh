#!/bin/bash

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
RESET='\033[0m'

echo -e "${BLUE}=== Rebuilding Bedrock Region Resources ===${RESET}"

# Lấy region từ cdk.json
BEDROCK_REGION=$(cat ./cdk/cdk.json | grep bedrockRegion | sed 's/.*"bedrockRegion": "\(.*\)",/\1/')
echo -e "${GREEN}Using Bedrock region: ${BEDROCK_REGION}${RESET}"

# Đi tới thư mục cdk
cd ./cdk

# Cài đặt dependencies nếu cần
if [ ! -d "node_modules" ]; then
  echo -e "${YELLOW}Installing dependencies...${RESET}"
  npm ci
fi

# Deploy BedrockRegionResourcesStack
echo -e "${GREEN}Deploying BedrockRegionResourcesStack to region ${BEDROCK_REGION}...${RESET}"
npx cdk deploy BedrockRegionResourcesStack --region ${BEDROCK_REGION}

# Kiểm tra kết quả
if [ $? -eq 0 ]; then
  echo -e "${GREEN}Successfully deployed BedrockRegionResourcesStack${RESET}"

  # Lấy tên bucket từ CloudFormation output
  BUCKET_NAME=$(aws cloudformation describe-stacks --stack-name BedrockRegionResourcesStack --region ${BEDROCK_REGION} --query "Stacks[0].Outputs[?OutputKey=='DocumentBucketName'].OutputValue" --output text)

  if [ ! -z "$BUCKET_NAME" ]; then
    echo -e "${GREEN}Document bucket name: ${BUCKET_NAME}${RESET}"
    echo -e "${GREEN}Checking if bucket exists...${RESET}"

    # Kiểm tra bucket có tồn tại không
    aws s3 ls s3://${BUCKET_NAME} --region ${BEDROCK_REGION}

    if [ $? -eq 0 ]; then
      echo -e "${GREEN}Bucket exists and is accessible${RESET}"
    else
      echo -e "${RED}Error: Cannot access bucket. Please check permissions.${RESET}"
    fi
  else
    echo -e "${RED}Error: Could not retrieve bucket name from stack outputs${RESET}"
  fi
else
  echo -e "${RED}Error: Failed to deploy BedrockRegionResourcesStack${RESET}"
fi

echo -e "${BLUE}=== Rebuild process completed ===${RESET}"