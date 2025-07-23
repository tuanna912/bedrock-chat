#!/bin/bash

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
RESET='\033[0m'

echo -e "${BLUE}=== Rebuilding Bedrock Region Resources (CloudShell Version) ===${RESET}"

# Sử dụng us-east-1 hoặc region khác nếu cần
BEDROCK_REGION="us-east-1"
echo -e "${GREEN}Using Bedrock region: ${BEDROCK_REGION}${RESET}"

# Tạo S3 bucket trực tiếp bằng AWS CLI
TIMESTAMP=$(date +%s)
STACK_NAME="BedrockRegionResourcesStack"
BUCKET_NAME="bedrock-documents-${TIMESTAMP}"
ACCESS_LOG_BUCKET_NAME="bedrock-access-logs-${TIMESTAMP}"

echo -e "${GREEN}Creating access log bucket: ${ACCESS_LOG_BUCKET_NAME}${RESET}"
aws s3api create-bucket --bucket ${ACCESS_LOG_BUCKET_NAME} --region ${BEDROCK_REGION}

echo -e "${GREEN}Creating document bucket: ${BUCKET_NAME}${RESET}"
aws s3api create-bucket --bucket ${BUCKET_NAME} --region ${BEDROCK_REGION}

# Cấu hình bucket properties
echo -e "${GREEN}Configuring bucket properties...${RESET}"

# Bật encryption
aws s3api put-bucket-encryption --bucket ${BUCKET_NAME} --server-side-encryption-configuration '{
  "Rules": [
    {
      "ApplyServerSideEncryptionByDefault": {
        "SSEAlgorithm": "AES256"
      },
      "BucketKeyEnabled": true
    }
  ]
}'

# Bật block public access
aws s3api put-public-access-block --bucket ${BUCKET_NAME} --public-access-block-configuration '{
  "BlockPublicAcls": true,
  "IgnorePublicAcls": true,
  "BlockPublicPolicy": true,
  "RestrictPublicBuckets": true
}'

# Bật logging
aws s3api put-bucket-logging --bucket ${BUCKET_NAME} --bucket-logging-status '{
  "LoggingEnabled": {
    "TargetBucket": "'${ACCESS_LOG_BUCKET_NAME}'",
    "TargetPrefix": "DocumentBucket/"
  }
}'

# Cập nhật CloudFormation stack để đăng ký bucket
echo -e "${GREEN}Updating CloudFormation stack with bucket information...${RESET}"

# Tạo template tạm thời
cat > template.yaml << EOF
Resources:
  DocumentBucket:
    Type: AWS::S3::Bucket
    DeletionPolicy: Retain
    Properties:
      BucketName: ${BUCKET_NAME}

Outputs:
  DocumentBucketName:
    Value: ${BUCKET_NAME}
    Description: Name of the document bucket
EOF

# Deploy stack
aws cloudformation deploy --template-file template.yaml --stack-name ${STACK_NAME} --region ${BEDROCK_REGION} --capabilities CAPABILITY_IAM

# Kiểm tra kết quả
if [ $? -eq 0 ]; then
  echo -e "${GREEN}Successfully deployed ${STACK_NAME}${RESET}"
  echo -e "${GREEN}Document bucket name: ${BUCKET_NAME}${RESET}"
  echo -e "${GREEN}Access log bucket name: ${ACCESS_LOG_BUCKET_NAME}${RESET}"

  # Kiểm tra bucket có tồn tại không
  aws s3 ls s3://${BUCKET_NAME} --region ${BEDROCK_REGION}

  if [ $? -eq 0 ]; then
    echo -e "${GREEN}Bucket exists and is accessible${RESET}"
  else
    echo -e "${RED}Error: Cannot access bucket. Please check permissions.${RESET}"
  fi
else
  echo -e "${RED}Error: Failed to deploy ${STACK_NAME}${RESET}"
fi

# Dọn dẹp
rm -f template.yaml

echo -e "${BLUE}=== Rebuild process completed ===${RESET}"
echo -e "${YELLOW}Note: You may need to update the bucket name in your application configuration.${RESET}"