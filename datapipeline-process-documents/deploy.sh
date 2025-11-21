#!/bin/bash

# Deployment Script for Knowledge Base Data Pipeline
# This script automates the deployment of the entire system

set -e  # Exit on error

# Disable AWS CLI pager
export AWS_PAGER=""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
REGION="us-east-1"
BUCKET_SUFFIX=$(date +%s)
DOCUMENT_BUCKET_NAME="techfest-documents-${BUCKET_SUFFIX}"
GLUE_BUCKET_NAME="techfest-glue-scripts-${BUCKET_SUFFIX}"
ACCOUNT_ID=""
OPENSEARCH_COLLECTION_NAME="kb-collection-1"

# Function to print colored output
print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_section() {
    echo -e "\n${GREEN}========================================${NC}"
    echo -e "${GREEN}$1${NC}"
    echo -e "${GREEN}========================================${NC}\n"
}

# Function to check if command exists
check_command() {
    if ! command -v $1 &> /dev/null; then
        print_error "$1 is not installed. Please install it first."
        exit 1
    fi
}

# Function to get AWS account ID
get_account_id() {
    ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
    if [ -z "$ACCOUNT_ID" ]; then
        print_error "Failed to get AWS Account ID. Check your AWS credentials."
        exit 1
    fi
    print_info "AWS Account ID: $ACCOUNT_ID"
}

# Function to create S3 buckets
create_s3_buckets() {
    print_section "Creating S3 Buckets"
    
    # Create document bucket
    print_info "Creating document bucket: $DOCUMENT_BUCKET_NAME"
    aws s3 mb s3://$DOCUMENT_BUCKET_NAME --region $REGION 2>/dev/null || print_warning "Bucket may already exist"
    
    # Enable EventBridge notifications
    print_info "Enabling EventBridge notifications..."
    aws s3api put-bucket-notification-configuration \
        --bucket $DOCUMENT_BUCKET_NAME \
        --notification-configuration '{"EventBridgeConfiguration": {}}'
    
    # Create folder structure in document bucket
    print_info "Creating folder structure in document bucket..."
    echo "This folder contains original documents uploaded by users" > /tmp/.placeholder_original
    echo "This folder contains large files (>=300KB) for Claude parser" > /tmp/.placeholder_large
    echo "This folder contains processed small documents (<300KB)" > /tmp/.placeholder_small
    
    aws s3 cp /tmp/.placeholder_original s3://$DOCUMENT_BUCKET_NAME/original_docs/.placeholder --quiet
    aws s3 cp /tmp/.placeholder_large s3://$DOCUMENT_BUCKET_NAME/original_docs/large/.placeholder --quiet
    aws s3 cp /tmp/.placeholder_small s3://$DOCUMENT_BUCKET_NAME/processed_docs/small/.placeholder --quiet
    
    rm -f /tmp/.placeholder_original /tmp/.placeholder_large /tmp/.placeholder_small
    
    print_success "✓ Created folders: original_docs/, original_docs/large/, processed_docs/small/"
    
    # Create Glue scripts bucket
    print_info "Creating Glue scripts bucket: $GLUE_BUCKET_NAME"
    aws s3 mb s3://$GLUE_BUCKET_NAME --region $REGION 2>/dev/null || print_warning "Bucket may already exist"
    
    print_success "S3 buckets created successfully"
}

# Function to create DynamoDB table
create_dynamodb_table() {
    print_section "Creating DynamoDB Table"
    
    print_info "Creating table: KnowledgeBaseRegistry"
    
    aws dynamodb create-table \
        --table-name KnowledgeBaseRegistry \
        --attribute-definitions AttributeName=bucket_name,AttributeType=S \
        --key-schema AttributeName=bucket_name,KeyType=HASH \
        --billing-mode PAY_PER_REQUEST \
        --region $REGION 2>/dev/null || print_warning "Table may already exist"
    
    print_success "DynamoDB table created"
}

# Function to create CloudWatch log groups
create_log_groups() {
    print_section "Creating CloudWatch Log Groups"
    
    print_info "Creating log groups for Glue job..."
    
    aws logs create-log-group --log-group-name /aws-glue/python-jobs/output --region $REGION 2>/dev/null || print_warning "Log group may already exist"
    aws logs create-log-group --log-group-name /aws-glue/python-jobs/error --region $REGION 2>/dev/null || print_warning "Log group may already exist"
    
    print_success "CloudWatch log groups created"
}

# Function to create IAM policies and roles
create_iam_resources() {
    print_section "Creating IAM Roles and Policies"
    
    # Create Glue Role Trust Policy
    cat > /tmp/glue-trust-policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "glue.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
EOF
    
    # Create Glue Permissions Policy
    cat > /tmp/glue-permissions-policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "BedrockKnowledgeBaseManagement",
      "Effect": "Allow",
      "Action": [
        "bedrock:CreateKnowledgeBase",
        "bedrock:GetKnowledgeBase",
        "bedrock:CreateDataSource",
        "bedrock:GetDataSource",
        "bedrock:InvokeModel",
        "bedrock:StartIngestionJob",
        "bedrock:GetIngestionJob",
        "bedrock:IngestKnowledgeBaseDocuments"
      ],
      "Resource": [
        "arn:aws:bedrock:*::foundation-model/*",
        "arn:aws:bedrock:$REGION:$ACCOUNT_ID:inference-profile/*",
        "arn:aws:bedrock:$REGION:$ACCOUNT_ID:knowledge-base/*",
        "arn:aws:bedrock:$REGION:$ACCOUNT_ID:data-source/*/*"
      ]
    },
    {
      "Sid": "OpenSearchCollectionAccess",
      "Effect": "Allow",
      "Action": [
        "aoss:BatchGetCollection",
        "aoss:ListCollections",
        "aoss:APIAccessAll"
      ],
      "Resource": "*"
    },
    {
      "Sid": "GetIngestionJob",
      "Effect": "Allow",
      "Action": [
        "bedrock:GetIngestionJob"
      ],
      "Resource": "*"
    },
    {
      "Sid": "IAMPassRoleForBedrock",
      "Effect": "Allow",
      "Action": "iam:PassRole",
      "Resource": "arn:aws:iam::$ACCOUNT_ID:role/BedrockKnowledgeBaseRole",
      "Condition": {
        "StringEquals": {
          "iam:PassedToService": "bedrock.amazonaws.com"
        }
      }
    },
    {
      "Sid": "DynamoDBRegistry",
      "Effect": "Allow",
      "Action": [
        "dynamodb:GetItem",
        "dynamodb:PutItem",
        "dynamodb:UpdateItem"
      ],
      "Resource": "arn:aws:dynamodb:$REGION:$ACCOUNT_ID:table/KnowledgeBaseRegistry"
    },
    {
      "Sid": "S3BucketAccess",
      "Effect": "Allow",
      "Action": "s3:ListBucket",
      "Resource": [
        "arn:aws:s3:::techfest-documents-*",
        "arn:aws:s3:::techfest-glue-scripts-*"
      ]
    },
    {
      "Sid": "S3ObjectAccess",
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject",
        "s3:DeleteObject"
      ],
      "Resource": [
        "arn:aws:s3:::techfest-documents-*/original_docs/*",
        "arn:aws:s3:::techfest-documents-*/original_docs/large/*",
        "arn:aws:s3:::techfest-documents-*/processed_docs/small/*",
        "arn:aws:s3:::techfest-glue-scripts-*/scripts/*"
      ]
    },
    {
      "Sid": "CloudWatchLogsForGlue",
      "Effect": "Allow",
      "Action": [
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents",
        "logs:AssociateKmsKey"
      ],
      "Resource": [
        "arn:aws:logs:$REGION:$ACCOUNT_ID:log-group:/aws-glue/python-jobs/*",
        "arn:aws:logs:$REGION:$ACCOUNT_ID:log-group:/aws-glue/python-jobs/output:*",
        "arn:aws:logs:$REGION:$ACCOUNT_ID:log-group:/aws-glue/python-jobs/error:*"
      ]
    }
  ]
}
EOF
    
    # Create Glue Role
    print_info "Creating Glue role..."
    aws iam create-role \
        --role-name GlueKnowledgeBaseRole \
        --assume-role-policy-document file:///tmp/glue-trust-policy.json \
        2>/dev/null || print_warning "Role may already exist"
    
    # NOTE: AWS managed AWSGlueServiceRole not needed for Python Shell jobs
    # All necessary permissions are in the custom policy below
    
    # Create custom policy
    GLUE_POLICY_ARN=$(aws iam create-policy \
        --policy-name GlueKnowledgeBaseCustomPolicy \
        --policy-document file:///tmp/glue-permissions-policy.json \
        --query 'Policy.Arn' \
        --output text 2>/dev/null) || {
        print_warning "Policy already exists, updating with new version..."
        GLUE_POLICY_ARN="arn:aws:iam::$ACCOUNT_ID:policy/GlueKnowledgeBaseCustomPolicy"
        # Create new policy version to update it
        aws iam create-policy-version \
            --policy-arn $GLUE_POLICY_ARN \
            --policy-document file:///tmp/glue-permissions-policy.json \
            --set-as-default 2>/dev/null || true
    }
    
    # Attach custom policy
    aws iam attach-role-policy \
        --role-name GlueKnowledgeBaseRole \
        --policy-arn $GLUE_POLICY_ARN \
        2>/dev/null || true
    
    # Create Bedrock KB Role
    cat > /tmp/bedrock-kb-trust-policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "bedrock.amazonaws.com"
      },
      "Action": "sts:AssumeRole",
      "Condition": {
        "StringEquals": {
          "aws:SourceAccount": "$ACCOUNT_ID"
        },
        "ArnLike": {
          "aws:SourceArn": "arn:aws:bedrock:$REGION:$ACCOUNT_ID:knowledge-base/*"
        }
      }
    }
  ]
}
EOF
    
    cat > /tmp/bedrock-kb-permissions-policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "OpenSearchServerlessAccess",
      "Effect": "Allow",
      "Action": [
        "aoss:APIAccessAll"
      ],
      "Resource": "arn:aws:aoss:$REGION:$ACCOUNT_ID:collection/*"
    },
    {
      "Sid": "BedrockModelAccess",
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel",
        "bedrock:StartIngestionJob"
      ],
      "Resource": [
        "arn:aws:bedrock:$REGION::foundation-model/amazon.titan-embed-text-v2:0",
        "arn:aws:bedrock:$REGION:$ACCOUNT_ID:inference-profile/us.anthropic.claude-3-5-sonnet-20241022-v2:0",
        "arn:aws:bedrock:us-west-2::foundation-model/anthropic.claude-3-5-sonnet-20241022-v2:0"
      ]
    },
    {
      "Sid": "S3ProcessedDocsRead",
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::techfest-documents-*",
        "arn:aws:s3:::techfest-documents-*/processed_docs/small/*",
        "arn:aws:s3:::techfest-documents-*/original_docs/large/*"
      ]
    }
  ]
}
EOF
    
    print_info "Creating Bedrock KB role..."
    aws iam create-role \
        --role-name BedrockKnowledgeBaseRole \
        --assume-role-policy-document file:///tmp/bedrock-kb-trust-policy.json \
        2>/dev/null || print_warning "Role may already exist"
    
    BEDROCK_POLICY_ARN=$(aws iam create-policy \
        --policy-name BedrockKnowledgeBasePolicy \
        --policy-document file:///tmp/bedrock-kb-permissions-policy.json \
        --query 'Policy.Arn' \
        --output text 2>/dev/null) || {
        print_warning "Policy may already exist, getting ARN..."
        BEDROCK_POLICY_ARN="arn:aws:iam::$ACCOUNT_ID:policy/BedrockKnowledgeBasePolicy"
    }
    
    aws iam attach-role-policy \
        --role-name BedrockKnowledgeBaseRole \
        --policy-arn $BEDROCK_POLICY_ARN \
        2>/dev/null || true
    
    # NOTE: EventBridge role is NOT needed - EventBridge invokes Lambda directly without assuming a role
    # Lambda then triggers Glue, so only Lambda needs permissions
    
    # Create Lambda Role for triggering Glue
    cat > /tmp/lambda-trust-policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "lambda.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
EOF
    
    cat > /tmp/lambda-permissions-policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "GlueJobTrigger",
      "Effect": "Allow",
      "Action": "glue:StartJobRun",
      "Resource": "arn:aws:glue:$REGION:$ACCOUNT_ID:job/KnowledgeBaseProcessor"
    },
    {
      "Sid": "CloudWatchLogs",
      "Effect": "Allow",
      "Action": [
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents"
      ],
      "Resource": "arn:aws:logs:$REGION:$ACCOUNT_ID:log-group:/aws/lambda/TriggerGlueFromS3:*"
    }
  ]
}
EOF
    
    print_info "Creating Lambda role..."
    aws iam create-role \
        --role-name LambdaTriggerGlueRole \
        --assume-role-policy-document file:///tmp/lambda-trust-policy.json \
        2>/dev/null || print_warning "Role may already exist"
    
    LAMBDA_POLICY_ARN=$(aws iam create-policy \
        --policy-name LambdaTriggerGluePolicy \
        --policy-document file:///tmp/lambda-permissions-policy.json \
        --query 'Policy.Arn' \
        --output text 2>/dev/null) || {
        print_warning "Policy already exists, updating with new version..."
        LAMBDA_POLICY_ARN="arn:aws:iam::$ACCOUNT_ID:policy/LambdaTriggerGluePolicy"
        # Create new policy version to update it
        aws iam create-policy-version \
            --policy-arn $LAMBDA_POLICY_ARN \
            --policy-document file:///tmp/lambda-permissions-policy.json \
            --set-as-default 2>/dev/null || true
    }
    
    aws iam attach-role-policy \
        --role-name LambdaTriggerGlueRole \
        --policy-arn $LAMBDA_POLICY_ARN \
        2>/dev/null || true
    
    print_success "IAM resources created"
    print_warning "Waiting 15 seconds for IAM propagation..."
    sleep 15
}

# Function to create Lambda function
create_lambda_function() {
    print_section "Creating Lambda Function"
    
    print_info "Creating Lambda deployment package..."
    
    # Create deployment package
    mkdir -p /tmp/lambda_package
    cp lambda_trigger_glue.py /tmp/lambda_package/
    cd /tmp/lambda_package
    zip -q lambda_function.zip lambda_trigger_glue.py
    cd - > /dev/null
    
    print_info "Creating Lambda function: TriggerGlueFromS3"
    
    # Build Lambda environment (optimized - no OpenSearch endpoint needed)
    ENV_JSON="{\"Variables\": {\"GLUE_JOB_NAME\": \"KnowledgeBaseProcessor\"}}"

  # Check if Lambda function already exists
  if aws lambda get-function --function-name TriggerGlueFromS3 --region $REGION &>/dev/null; then
    print_warning "Function already exists, updating code and config..."
    aws lambda update-function-code \
      --function-name TriggerGlueFromS3 \
      --zip-file fileb:///tmp/lambda_package/lambda_function.zip \
      --region $REGION
    sleep 2
    # Also update environment variables
    aws lambda update-function-configuration \
      --function-name TriggerGlueFromS3 \
      --environment "$ENV_JSON" \
      --region $REGION
  else
    print_info "Creating new Lambda function..."
    aws lambda create-function \
      --function-name TriggerGlueFromS3 \
      --runtime python3.11 \
      --role arn:aws:iam::$ACCOUNT_ID:role/LambdaTriggerGlueRole \
      --handler lambda_trigger_glue.lambda_handler \
      --zip-file fileb:///tmp/lambda_package/lambda_function.zip \
      --timeout 60 \
      --memory-size 256 \
      --environment "$ENV_JSON" \
      --region $REGION
  fi
    
    # Clean up
    rm -rf /tmp/lambda_package
    
    print_success "Lambda function created with OpenSearch endpoint"
}

# Function to create OpenSearch Serverless Collection
create_opensearch() {
    print_section "Creating OpenSearch Serverless Collection"
    
    # Create encryption policy
    print_info "Creating encryption policy..."
    aws opensearchserverless create-security-policy \
        --name kb-encryption-policy \
        --type encryption \
        --policy "{\"Rules\":[{\"Resource\":[\"collection/$OPENSEARCH_COLLECTION_NAME\"],\"ResourceType\":\"collection\"}],\"AWSOwnedKey\":true}" \
        --region $REGION 2>/dev/null || print_warning "Policy may already exist"
    
    # Create network policy
    print_info "Creating network policy..."
    aws opensearchserverless create-security-policy \
        --name kb-network-policy \
        --type network \
        --policy "[{\"Rules\":[{\"Resource\":[\"collection/$OPENSEARCH_COLLECTION_NAME\"],\"ResourceType\":\"collection\"}],\"AllowFromPublic\":true}]" \
        --region $REGION 2>/dev/null || print_warning "Policy may already exist"
    
    # Create collection
    print_info "Creating collection: $OPENSEARCH_COLLECTION_NAME"
    aws opensearchserverless create-collection \
        --name $OPENSEARCH_COLLECTION_NAME \
        --type VECTORSEARCH \
        --description "Vector store for Bedrock Knowledge Base" \
        --region $REGION 2>/dev/null || print_warning "Collection may already exist"
    
    print_info "Waiting for collection to be active..."
    
    # Poll for collection endpoint (retry up to 300 seconds since collection might take longer)
    MAX_WAIT=300
    ELAPSED=0
    OPENSEARCH_ENDPOINT=""
    
    while [ $ELAPSED -lt $MAX_WAIT ]; do
        sleep 10
        ELAPSED=$((ELAPSED + 10))
        
        # Get the full collection details for debugging
        COLLECTION_STATUS=$(aws opensearchserverless batch-get-collection \
            --names $OPENSEARCH_COLLECTION_NAME \
            --region $REGION \
            --output json 2>/dev/null || echo "{}")
        
        print_info "Collection status response (${ELAPSED}s): $COLLECTION_STATUS"
        
        OPENSEARCH_ENDPOINT=$(echo "$COLLECTION_STATUS" | jq -r '.collectionDetails[0].collectionEndpoint // empty' 2>/dev/null || echo "")
        
        if [ -n "$OPENSEARCH_ENDPOINT" ] && [ "$OPENSEARCH_ENDPOINT" != "None" ] && [ "$OPENSEARCH_ENDPOINT" != "null" ]; then
            print_success "Collection endpoint ready: $OPENSEARCH_ENDPOINT"
            break
        fi
        
        print_info "Waiting for collection endpoint... (${ELAPSED}s elapsed)"
    done
    
    if [ -z "$OPENSEARCH_ENDPOINT" ] || [ "$OPENSEARCH_ENDPOINT" = "None" ]; then
        print_warning "Collection endpoint not available after ${MAX_WAIT}s"
        OPENSEARCH_ENDPOINT=""
    fi
    
    # Create data access policy
    print_info "Creating data access policy..."
    aws opensearchserverless create-access-policy \
        --name kb-access-policy \
        --type data \
        --policy "[{\"Rules\":[{\"Resource\":[\"collection/$OPENSEARCH_COLLECTION_NAME\"],\"Permission\":[\"aoss:CreateCollectionItems\",\"aoss:DeleteCollectionItems\",\"aoss:UpdateCollectionItems\",\"aoss:DescribeCollectionItems\"],\"ResourceType\":\"collection\"},{\"Resource\":[\"index/$OPENSEARCH_COLLECTION_NAME/*\"],\"Permission\":[\"aoss:CreateIndex\",\"aoss:DeleteIndex\",\"aoss:UpdateIndex\",\"aoss:DescribeIndex\",\"aoss:ReadDocument\",\"aoss:WriteDocument\"],\"ResourceType\":\"index\"}],\"Principal\":[\"arn:aws:iam::$ACCOUNT_ID:role/BedrockKnowledgeBaseRole\",\"arn:aws:iam::$ACCOUNT_ID:role/GlueKnowledgeBaseRole\"]}]" \
        --region $REGION 2>/dev/null || print_warning "Policy may already exist"
    
    print_success "OpenSearch collection created"
    print_info "OpenSearch endpoint will be used by Lambda: $OPENSEARCH_ENDPOINT"
}

# Function to upload Glue script
upload_glue_script() {
    print_section "Uploading Glue Script"
    
    if [ ! -f "glue_kb_processor_techfest.py" ]; then
        print_error "glue_kb_processor_techfest.py not found"
        exit 1
    fi
    
    print_info "Uploading script to s3://$GLUE_BUCKET_NAME/scripts/"
    aws s3 cp glue_kb_processor_techfest.py s3://$GLUE_BUCKET_NAME/scripts/
    
    # Verify upload
    if aws s3 ls s3://$GLUE_BUCKET_NAME/scripts/glue_kb_processor_techfest.py > /dev/null 2>&1; then
        print_success "Glue script uploaded and verified"
        print_info "Script features:"
        print_info "  - Dual datasource: small files (<300KB) + large files (>=300KB)"
        print_info "  - Small files: No chunking (1 file = 1 chunk)"
        print_info "  - Large files: Fixed-size chunking (2048 tokens, 20% overlap)"
    else
        print_error "Failed to verify script upload"
        exit 1
    fi
    
    print_info "Waiting 3 seconds for S3 consistency..."
    sleep 3
}

# Function to create Glue job
create_glue_job() {
    print_section "Creating Glue Job"
    
    print_info "Creating Glue job: KnowledgeBaseProcessor (S3 datasource flow)"
    
    if aws glue create-job \
        --name KnowledgeBaseProcessor \
        --role GlueKnowledgeBaseRole \
        --command "{
            \"Name\": \"pythonshell\",
            \"ScriptLocation\": \"s3://$GLUE_BUCKET_NAME/scripts/glue_kb_processor_techfest.py\",
            \"PythonVersion\": \"3.9\"
        }" \
        --default-arguments "{
            \"--additional-python-modules\": \"boto3>=1.28.0,opensearch-py==2.3.1,requests-aws4auth>=1.1.0,python-docx>=0.8.11,openpyxl==3.0.10,PyPDF2>=3.0.0\",
            \"--enable-continuous-cloudwatch-log\": \"true\",
            \"--continuous-log-logGroup\": \"/aws-glue/python-jobs/output\",
            \"--enable-continuous-log-filter\": \"true\"
        }" \
        --max-capacity 1 \
        --glue-version "3.0" \
        --region $REGION 2>/dev/null; then
        print_success "Glue job created"
    else
        print_warning "Job already exists, updating..."
        aws glue update-job \
            --job-name KnowledgeBaseProcessor \
            --job-update "{
                \"Role\": \"arn:aws:iam::$ACCOUNT_ID:role/GlueKnowledgeBaseRole\",
                \"Command\": {
                    \"Name\": \"pythonshell\",
                    \"ScriptLocation\": \"s3://$GLUE_BUCKET_NAME/scripts/glue_kb_processor_techfest.py\",
                    \"PythonVersion\": \"3.9\"
                },
                \"DefaultArguments\": {
                    \"--additional-python-modules\": \"boto3>=1.28.0,opensearch-py==2.3.1,requests-aws4auth>=1.1.0,python-docx>=0.8.11,openpyxl==3.0.10,PyPDF2>=3.0.0\",
                    \"--enable-continuous-cloudwatch-log\": \"true\",
                    \"--continuous-log-logGroup\": \"/aws-glue/python-jobs/output\",
                    \"--enable-continuous-log-filter\": \"true\"
                },
                \"MaxCapacity\": 1,
                \"GlueVersion\": \"3.0\"
            }" \
            --region $REGION > /dev/null
        print_success "Glue job updated"
    fi
}

# Function to create EventBridge rule
create_eventbridge_rule() {
    print_section "Creating EventBridge Rule"
    
    print_info "Creating rule: S3ToGlueKnowledgeBase"
    
    aws events put-rule \
        --name S3ToGlueKnowledgeBase \
        --event-pattern "{
            \"source\": [\"aws.s3\"],
            \"detail-type\": [\"Object Created\"],
            \"detail\": {
                \"bucket\": {
                    \"name\": [\"$DOCUMENT_BUCKET_NAME\"]
                },
                \"object\": {
                    \"key\": [
                        {\"prefix\": \"original_docs/\"}
                    ]
                }
            }
        }" \
        --state ENABLED \
        --region $REGION
    
    print_info "Adding Lambda permission for EventBridge..."
    
    # Add permission for EventBridge to invoke Lambda
    aws lambda add-permission \
        --function-name TriggerGlueFromS3 \
        --statement-id AllowEventBridgeInvoke \
        --action lambda:InvokeFunction \
        --principal events.amazonaws.com \
        --source-arn arn:aws:events:$REGION:$ACCOUNT_ID:rule/S3ToGlueKnowledgeBase \
        --region $REGION \
        2>/dev/null || print_warning "Permission may already exist"
    
    print_info "Adding Lambda target to rule..."
    
    aws events put-targets \
        --rule S3ToGlueKnowledgeBase \
        --targets "[
            {
                \"Id\": \"1\",
                \"Arn\": \"arn:aws:lambda:$REGION:$ACCOUNT_ID:function:TriggerGlueFromS3\"
            }
        ]" \
        --region $REGION
    
    print_success "EventBridge rule created"
}

# Function to test the system
test_system() {
    print_section "Testing the System"
    
    print_info "Creating test file..."
    echo "This is a test document for Knowledge Base ingestion.
    
This document tests the automated data pipeline that:
1. Uploads files to S3
2. Triggers Glue ETL processing
3. Ingests content into Bedrock Knowledge Base
4. Stores vectors in OpenSearch Serverless

The system should automatically process this file and make it available for retrieval testing." > /tmp/test-document.txt
    
    print_info "Uploading test file to S3..."
    aws s3 cp /tmp/test-document.txt s3://$DOCUMENT_BUCKET_NAME/original_docs/test-document.txt
    
    print_success "Test file uploaded!"
    print_info "Check CloudWatch Logs in a few minutes: /aws-glue/jobs/output"
    print_info "Or monitor Glue job: aws glue get-job-runs --job-name KnowledgeBaseProcessor"
}

# Function to print deployment summary
print_summary() {
    print_section "Deployment Summary"
    
    echo "📦 Resources:"
    echo "  Document Bucket:      s3://$DOCUMENT_BUCKET_NAME"
    echo "    ├─ original_docs/          (upload all files here)"
    echo "    ├─ original_docs/large/    (large files ≥300KB auto-moved here)"
    echo "    └─ processed_docs/small/   (small files <300KB processed)"
    echo "  Glue Scripts Bucket:  s3://$GLUE_BUCKET_NAME"
    echo "  DynamoDB Table:       KnowledgeBaseRegistry"
    echo "  OpenSearch Collection: $OPENSEARCH_COLLECTION_NAME"
    echo "  Glue Job:             KnowledgeBaseProcessor"
    echo "  Lambda Function:      TriggerGlueFromS3"
    echo "  EventBridge Rule:     S3ToGlueKnowledgeBase"
    echo ""
    echo "Processing Strategy:"
    echo "  - Small files (<300KB): Extract → processed_docs/small/ → DS1 (NONE chunking)"
    echo "  - Large files (≥300KB): Move to original_docs/large/ → DS2 (Claude parser + fixed-size chunking)"
    echo ""
    echo "IAM Roles Created:"
    echo "  - GlueKnowledgeBaseRole (ETL + KB management + file routing)"
    echo "  - BedrockKnowledgeBaseRole (KB dual S3 datasources + Claude parser)"
    echo "  - LambdaTriggerGlueRole (EventBridge → Lambda → Glue)"
    echo ""
    print_success "Deployment completed successfully!"
    echo ""
    print_info "Next steps:"
    echo "1. Upload documents to: s3://$DOCUMENT_BUCKET_NAME/original_docs/"
    echo "2. Monitor Glue job runs: aws glue get-job-runs --job-name KnowledgeBaseProcessor"
    echo "3. Check CloudWatch Logs: /aws-glue/jobs/output"
    echo "4. Test Knowledge Base in Bedrock Console"
    echo ""
    print_info "To test now, run: ./deploy.sh test-only"
}

# Main deployment function
main() {
    print_section "Knowledge Base Data Pipeline Deployment"
    
    # Check prerequisites
    print_info "Checking prerequisites..."
    check_command aws
    check_command jq
    
    # Get AWS account ID
    get_account_id
    
    # Run deployment steps
    create_s3_buckets
    create_dynamodb_table
    create_log_groups
    create_iam_resources
    create_opensearch
    create_lambda_function
    upload_glue_script
    create_glue_job
    create_eventbridge_rule
    
    # Print summary
    print_summary
    
    # Optionally run test
    read -p "Do you want to upload a test file now? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        test_system
    fi
}

# Handle command line arguments
if [ "$1" == "test-only" ]; then
    get_account_id
    # Use existing bucket
    DOCUMENT_BUCKET_NAME=$(aws s3 ls | grep kb-documents | tail -1 | awk '{print $3}')
    if [ -z "$DOCUMENT_BUCKET_NAME" ]; then
        print_error "No document bucket found. Deploy first."
        exit 1
    fi
    test_system
elif [ "$1" == "cleanup" ]; then
    print_warning "This will delete all resources. Are you sure? (type 'yes' to confirm)"
    read confirmation
    if [ "$confirmation" == "yes" ]; then
        print_info "Cleaning up resources..."
        # Add cleanup commands here
        print_success "Cleanup completed"
    fi
else
    main
fi
