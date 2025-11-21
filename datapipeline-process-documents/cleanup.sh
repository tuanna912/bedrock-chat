#!/bin/bash

# Cleanup Script for KB Data Pipeline
# WARNING: This will delete all resources created by the deployment
#
# Usage:
#   ./cleanup.sh           - Interactive cleanup with confirmation
#   ./cleanup.sh --list    - List resources without deleting

set -e

# Disable AWS CLI pager
export AWS_PAGER=""

# Check for list-only mode
LIST_ONLY=false
if [ "$1" = "--list" ] || [ "$1" = "-l" ]; then
    LIST_ONLY=true
fi

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

# Get configuration
REGION="us-east-1"
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

echo "======================================"
echo "KB Data Pipeline Cleanup Script"
echo "======================================"
echo ""
echo "Scanning for resources in account: $ACCOUNT_ID"
echo "Region: $REGION"
echo ""

# List resources to be deleted
print_info "Resources found:"
echo ""

# S3 Buckets
DOCUMENT_BUCKETS=$(aws s3 ls | grep -E "techfest-documents" | awk '{print $3}' | tr '\n' ' ')
GLUE_BUCKETS=$(aws s3 ls | grep -E "techfest-glue-scripts" | awk '{print $3}' | tr '\n' ' ')
if [ -n "$DOCUMENT_BUCKETS" ] || [ -n "$GLUE_BUCKETS" ]; then
    echo "  📦 S3 Buckets:"
    [ -n "$DOCUMENT_BUCKETS" ] && echo "     - $DOCUMENT_BUCKETS"
    [ -n "$GLUE_BUCKETS" ] && echo "     - $GLUE_BUCKETS"
fi

# Lambda Functions
LAMBDA_EXISTS=$(aws lambda get-function --function-name TriggerGlueFromS3 --region $REGION 2>/dev/null && echo "yes" || echo "no")
if [ "$LAMBDA_EXISTS" = "yes" ]; then
    echo "  λ Lambda: TriggerGlueFromS3"
fi

# Glue Jobs
GLUE_JOB=$(aws glue get-job --job-name KnowledgeBaseProcessor --region $REGION 2>/dev/null && echo "KnowledgeBaseProcessor" || echo "")
[ -n "$GLUE_JOB" ] && echo "  🔧 Glue Job: $GLUE_JOB"

# DynamoDB Table
DYNAMODB_TABLE=$(aws dynamodb describe-table --table-name KnowledgeBaseRegistry --region $REGION 2>/dev/null && echo "KnowledgeBaseRegistry" || echo "")
[ -n "$DYNAMODB_TABLE" ] && echo "  🗄️  DynamoDB: $DYNAMODB_TABLE"

# OpenSearch Collection
OPENSEARCH_COLLECTION=$(aws opensearchserverless batch-get-collection --names kb-collection-1 --region $REGION 2>/dev/null | grep -q "kb-collection-1" && echo "kb-collection-1" || echo "")
[ -n "$OPENSEARCH_COLLECTION" ] && echo "  🔍 OpenSearch: $OPENSEARCH_COLLECTION"

# IAM Roles
echo "  👤 IAM Roles: GlueKnowledgeBaseRole, BedrockKnowledgeBaseRole, EventBridgeGlueRole, LambdaTriggerGlueRole"

# Knowledge Bases
KB_COUNT=$(aws bedrock-agent list-knowledge-bases --region $REGION --query 'length(knowledgeBaseSummaries)' --output text 2>/dev/null || echo "0")
[ "$KB_COUNT" != "0" ] && echo "  🧠 Knowledge Bases: $KB_COUNT found (with dual datasources)"

echo ""

# If list-only mode, exit here
if [ "$LIST_ONLY" = true ]; then
    print_info "List-only mode. No resources will be deleted."
    echo ""
    echo "To delete these resources, run: ./cleanup.sh"
    exit 0
fi

echo "⚠️  WARNING: This will permanently delete all resources above!"
echo ""
print_warning "This action CANNOT be undone!"
echo ""
read -p "Type 'DELETE' to confirm: " confirmation

if [ "$confirmation" != "DELETE" ]; then
    echo "Cleanup cancelled."
    exit 0
fi

echo ""
echo "Starting cleanup..."
echo ""

# Function to safely delete resource
safe_delete() {
    local resource_name=$1
    local delete_command=$2
    
    echo -n "Deleting $resource_name... "
    if eval "$delete_command" 2>/dev/null; then
        print_success "Deleted"
    else
        print_warning "Not found or already deleted"
    fi
}

# 1. Delete EventBridge rule and targets
print_info "Step 1: Removing EventBridge rule"
aws events remove-targets \
    --rule S3ToGlueKnowledgeBase \
    --ids 1 \
    --region $REGION 2>/dev/null || true

safe_delete "EventBridge rule" \
    "aws events delete-rule --name S3ToGlueKnowledgeBase --region $REGION"

# 2. Delete Lambda function
print_info "Step 2: Removing Lambda function"
safe_delete "Lambda function" \
    "aws lambda delete-function --function-name TriggerGlueFromS3 --region $REGION"

# 3. Delete Glue job
print_info "Step 3: Removing Glue job"
safe_delete "Glue job" \
    "aws glue delete-job --job-name KnowledgeBaseProcessor --region $REGION"

# 4. Delete S3 buckets
print_info "Step 4: Removing S3 buckets"

# Find document buckets
DOCUMENT_BUCKETS=$(aws s3 ls | grep -E "techfest-documents|testfest-documents" | awk '{print $3}')
for BUCKET in $DOCUMENT_BUCKETS; do
    echo "  Emptying bucket: $BUCKET"
    echo "    - Removing original_docs/ folder..."
    aws s3 rm s3://$BUCKET/original_docs/ --recursive --quiet 2>/dev/null || true
    echo "    - Removing processed_docs/small/ folder..."
    aws s3 rm s3://$BUCKET/processed_docs/small/ --recursive --quiet 2>/dev/null || true
    echo "    - Removing all remaining objects..."
    aws s3 rm s3://$BUCKET --recursive --quiet 2>/dev/null || true
    safe_delete "S3 bucket $BUCKET" \
        "aws s3 rb s3://$BUCKET --force"
done

# Find Glue script buckets
GLUE_BUCKETS=$(aws s3 ls | grep -E "techfest-glue-scripts|testfest-glue-scripts" | awk '{print $3}')
for BUCKET in $GLUE_BUCKETS; do
    echo "  Emptying bucket: $BUCKET"
    aws s3 rm s3://$BUCKET --recursive --quiet 2>/dev/null || true
    safe_delete "S3 bucket $BUCKET" \
        "aws s3 rb s3://$BUCKET --force"
done

# 5. Delete DynamoDB table
print_info "Step 5: Removing DynamoDB table"
safe_delete "DynamoDB table" \
    "aws dynamodb delete-table --table-name KnowledgeBaseRegistry --region $REGION"

# 6. Delete Knowledge Bases created by this pipeline
print_info "Step 6: Removing Knowledge Bases created by pipeline"

# Get all KBs and filter by name pattern (kb-techfest-documents-* or kb-techfest-glue-scripts-*)
KB_LIST=$(aws bedrock-agent list-knowledge-bases \
    --region $REGION \
    --query 'knowledgeBaseSummaries[*].[knowledgeBaseId,name]' \
    --output text 2>/dev/null)

if [ -n "$KB_LIST" ]; then
    # Filter only KBs created by this pipeline (name starts with kb-techfest-)
    PIPELINE_KBS=$(echo "$KB_LIST" | grep -E "kb-techfest176" || true)
    
    if [ -n "$PIPELINE_KBS" ]; then
        echo ""
        echo "Found Knowledge Bases created by this pipeline:"
        echo "$PIPELINE_KBS" | while read KB_ID KB_NAME; do
            echo "  - $KB_NAME (ID: $KB_ID)"
        done
        echo ""
        
        read -p "Delete these Knowledge Bases? (y/n) " -n 1 -r
        echo
        
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            echo "$PIPELINE_KBS" | while read KB_ID KB_NAME; do
                echo "  Deleting KB: $KB_NAME"
                
                # Delete data sources
                DS_IDS=$(aws bedrock-agent list-data-sources \
                    --knowledge-base-id $KB_ID \
                    --query 'dataSourceSummaries[*].dataSourceId' \
                    --output text \
                    --region $REGION 2>/dev/null)
                
                for DS_ID in $DS_IDS; do
                    echo "    Deleting data source: $DS_ID"
                    aws bedrock-agent delete-data-source \
                        --knowledge-base-id $KB_ID \
                        --data-source-id $DS_ID \
                        --region $REGION 2>/dev/null || true
                done
                
                # Delete KB
                aws bedrock-agent delete-knowledge-base \
                    --knowledge-base-id $KB_ID \
                    --region $REGION 2>/dev/null || true
                
                print_success "Deleted KB: $KB_NAME"
            done
        else
            print_warning "Skipping Knowledge Base deletion"
        fi
    else
        print_info "No Knowledge Bases created by this pipeline found"
    fi
else
    print_info "No Knowledge Bases found"
fi

# 7. Delete OpenSearch collection and policies
print_info "Step 7: Removing OpenSearch collection and policies"

# Step 7a: Delete access policy first
echo "  Deleting access policy..."
safe_delete "OpenSearch access policy" \
    "aws opensearchserverless delete-access-policy --name kb-access-policy --type data --region $REGION"

# Step 7b: Delete collection
echo "  Deleting collection..."
COLLECTION_ID=$(aws opensearchserverless batch-get-collection --names kb-collection-1 --region $REGION --query 'collectionDetails[0].id' --output text 2>/dev/null || echo "")
if [ -n "$COLLECTION_ID" ] && [ "$COLLECTION_ID" != "None" ]; then
    safe_delete "OpenSearch collection kb-collection-1" \
        "aws opensearchserverless delete-collection --id $COLLECTION_ID --region $REGION"
    echo "  Waiting for collection deletion..."
    sleep 10
else
    print_warning "Collection not found or already deleted"
fi

# Step 7c: Delete network and encryption policies
echo "  Deleting network policy..."
safe_delete "OpenSearch network policy" \
    "aws opensearchserverless delete-security-policy --name kb-network-policy --type network --region $REGION"

echo "  Deleting encryption policy..."
safe_delete "OpenSearch encryption policy" \
    "aws opensearchserverless delete-security-policy --name kb-encryption-policy --type encryption --region $REGION"

# 8. Detach and delete IAM policies
print_info "Step 8: Removing IAM resources"

# Glue role
echo "  Detaching policies from GlueKnowledgeBaseRole..."
# Check for legacy managed policy (no longer attached in optimized version)
aws iam detach-role-policy \
    --role-name GlueKnowledgeBaseRole \
    --policy-arn arn:aws:iam::aws:policy/service-role/AWSGlueServiceRole \
    2>/dev/null || true

aws iam detach-role-policy \
    --role-name GlueKnowledgeBaseRole \
    --policy-arn arn:aws:iam::$ACCOUNT_ID:policy/GlueKnowledgeBaseCustomPolicy \
    2>/dev/null || true

safe_delete "GlueKnowledgeBaseRole" \
    "aws iam delete-role --role-name GlueKnowledgeBaseRole"

safe_delete "GlueKnowledgeBaseCustomPolicy" \
    "aws iam delete-policy --policy-arn arn:aws:iam::$ACCOUNT_ID:policy/GlueKnowledgeBaseCustomPolicy"

# Bedrock role
echo "  Detaching policies from BedrockKnowledgeBaseRole..."
aws iam detach-role-policy \
    --role-name BedrockKnowledgeBaseRole \
    --policy-arn arn:aws:iam::$ACCOUNT_ID:policy/BedrockKnowledgeBasePolicy \
    2>/dev/null || true

safe_delete "BedrockKnowledgeBaseRole" \
    "aws iam delete-role --role-name BedrockKnowledgeBaseRole"

safe_delete "BedrockKnowledgeBasePolicy" \
    "aws iam delete-policy --policy-arn arn:aws:iam::$ACCOUNT_ID:policy/BedrockKnowledgeBasePolicy"

# EventBridge role (legacy - no longer created in new deployments)
echo "  Checking for legacy EventBridge role..."
if aws iam get-role --role-name EventBridgeGlueRole 2>/dev/null; then
    aws iam detach-role-policy \
        --role-name EventBridgeGlueRole \
        --policy-arn arn:aws:iam::$ACCOUNT_ID:policy/EventBridgeGluePolicy \
        2>/dev/null || true
    
    safe_delete "EventBridgeGlueRole" \
        "aws iam delete-role --role-name EventBridgeGlueRole"
    
    safe_delete "EventBridgeGluePolicy" \
        "aws iam delete-policy --policy-arn arn:aws:iam::$ACCOUNT_ID:policy/EventBridgeGluePolicy"
else
    print_info "EventBridge role not found (not needed in optimized version)"
fi

# Lambda role
echo "  Detaching policies from LambdaTriggerGlueRole..."
aws iam detach-role-policy \
    --role-name LambdaTriggerGlueRole \
    --policy-arn arn:aws:iam::$ACCOUNT_ID:policy/LambdaTriggerGluePolicy \
    2>/dev/null || true

safe_delete "LambdaTriggerGlueRole" \
    "aws iam delete-role --role-name LambdaTriggerGlueRole"

safe_delete "LambdaTriggerGluePolicy" \
    "aws iam delete-policy --policy-arn arn:aws:iam::$ACCOUNT_ID:policy/LambdaTriggerGluePolicy"

# 9. Delete CloudWatch log groups
print_info "Step 9: Removing CloudWatch log groups"

# Delete all Glue-related log groups
echo "  Scanning for Glue log groups..."
GLUE_LOG_GROUPS=$(aws logs describe-log-groups \
    --region $REGION \
    --query 'logGroups[?starts_with(logGroupName, `/aws-glue/`)].logGroupName' \
    --output text 2>/dev/null)

for LOG_GROUP in $GLUE_LOG_GROUPS; do
    safe_delete "CloudWatch log group $LOG_GROUP" \
        "aws logs delete-log-group --log-group-name '$LOG_GROUP' --region $REGION"
done

# Delete specific log groups created by deployment
echo "  Deleting specific log groups..."
safe_delete "Glue output logs" \
    "aws logs delete-log-group --log-group-name /aws-glue/jobs/output --region $REGION"

safe_delete "Glue error logs" \
    "aws logs delete-log-group --log-group-name /aws-glue/jobs/error --region $REGION"

safe_delete "Glue Python jobs output" \
    "aws logs delete-log-group --log-group-name /aws-glue/python-jobs/output --region $REGION"

safe_delete "Glue Python jobs error" \
    "aws logs delete-log-group --log-group-name /aws-glue/python-jobs/error --region $REGION"

safe_delete "Lambda logs" \
    "aws logs delete-log-group --log-group-name /aws/lambda/TriggerGlueFromS3 --region $REGION"

# Delete any KnowledgeBaseProcessor-specific logs
echo "  Scanning for KnowledgeBaseProcessor logs..."
KB_PROCESSOR_LOGS=$(aws logs describe-log-groups \
    --region $REGION \
    --query 'logGroups[?contains(logGroupName, `KnowledgeBaseProcessor`)].logGroupName' \
    --output text 2>/dev/null)

for LOG_GROUP in $KB_PROCESSOR_LOGS; do
    safe_delete "KB Processor log $LOG_GROUP" \
        "aws logs delete-log-group --log-group-name '$LOG_GROUP' --region $REGION"
done

# 10. Clean up temp files
print_info "Step 10: Cleaning up temporary files"
rm -f /tmp/glue-trust-policy.json
rm -f /tmp/glue-permissions-policy.json
rm -f /tmp/bedrock-kb-trust-policy.json
rm -f /tmp/bedrock-kb-permissions-policy.json
rm -f /tmp/eventbridge-trust-policy.json
rm -f /tmp/eventbridge-permissions-policy.json
rm -f /tmp/lambda-trust-policy.json
rm -f /tmp/lambda-permissions-policy.json
rm -f /tmp/kb-test-*.txt
rm -rf /tmp/lambda_package
print_success "Temp files cleaned"

echo ""
echo "======================================"
print_success "Cleanup completed!"
echo "======================================"
echo ""
echo "Deleted resources:"
echo "  ✓ EventBridge rules"
echo "  ✓ Lambda functions"
echo "  ✓ Glue jobs"
echo "  ✓ S3 buckets (original_docs/, original_docs/large/, processed_docs/small/)"
echo "  ✓ DynamoDB tables"
echo "  ✓ OpenSearch collections and policies"
echo "  ✓ IAM roles and policies"
echo "  ✓ CloudWatch log groups"
echo ""
print_warning "Note: Some resources may take a few minutes to fully delete."
echo ""
