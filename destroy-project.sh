#!/bin/bash

# Script to destroy all AWS services and resources deployed for this project

set -e

echo "==================================================="
echo "WARNING: This script will destroy ALL AWS resources"
echo "deployed for this project. This action is IRREVERSIBLE."
echo "==================================================="
echo ""
echo "Please type 'DESTROY' to confirm: "
read -r confirmation

if [ "$confirmation" != "DESTROY" ]; then
  echo "Destruction cancelled."
  exit 1
fi

# Get environment variables
ENV_NAME=${ENV_NAME:-default}
BEDROCK_REGION=${BEDROCK_REGION:-us-east-1}
DEFAULT_REGION=${AWS_REGION:-$(aws configure get region || echo "us-east-1")}
ACCOUNT_ID=$(aws sts get-caller-identity --query "Account" --output text)

echo "Using Environment: $ENV_NAME"
echo "AWS Account: $ACCOUNT_ID"
echo "Default Region: $DEFAULT_REGION"
echo "Bedrock Region: $BEDROCK_REGION"
echo ""

# Calculate stack name prefix
if [ "$ENV_NAME" = "default" ]; then
  STACK_PREFIX=""
else
  STACK_PREFIX="$ENV_NAME-"
fi

echo "Stack prefix: $STACK_PREFIX"
echo ""

# Function to empty and delete S3 bucket
empty_and_delete_bucket() {
  bucket_name=$1
  echo "Checking if bucket exists: $bucket_name"

  if aws s3api head-bucket --bucket "$bucket_name" 2>/dev/null; then
    echo "Emptying bucket: $bucket_name"
    aws s3 rm "s3://$bucket_name" --recursive

    echo "Removing bucket versioning"
    aws s3api put-bucket-versioning --bucket "$bucket_name" --versioning-configuration Status=Suspended

    echo "Deleting all versions"
    versions=$(aws s3api list-object-versions --bucket "$bucket_name" --output json)

    delete_markers=$(echo "$versions" | jq -r '.DeleteMarkers[] | "\(.Key) \(.VersionId)"' 2>/dev/null || echo "")
    if [ -n "$delete_markers" ]; then
      echo "$delete_markers" | while read -r key version_id; do
        aws s3api delete-object --bucket "$bucket_name" --key "$key" --version-id "$version_id"
      done
    fi

    object_versions=$(echo "$versions" | jq -r '.Versions[] | "\(.Key) \(.VersionId)"' 2>/dev/null || echo "")
    if [ -n "$object_versions" ]; then
      echo "$object_versions" | while read -r key version_id; do
        aws s3api delete-object --bucket "$bucket_name" --key "$key" --version-id "$version_id"
      done
    fi

    echo "Deleting bucket: $bucket_name"
    aws s3api delete-bucket --bucket "$bucket_name"
  else
    echo "Bucket does not exist: $bucket_name"
  fi
}

# Function to delete CloudFormation stack with retries
delete_stack() {
  stack_name=$1
  region=$2
  max_attempts=3

  echo "Attempting to delete stack: $stack_name in region $region"

  for ((attempt=1; attempt<=max_attempts; attempt++)); do
    echo "Attempt $attempt of $max_attempts..."

    if ! aws cloudformation describe-stacks --stack-name "$stack_name" --region "$region" &>/dev/null; then
      echo "Stack $stack_name does not exist in region $region"
      return 0
    fi

    aws cloudformation delete-stack --stack-name "$stack_name" --region "$region"

    # Wait for deletion to complete or fail
    while true; do
      if ! aws cloudformation describe-stacks --stack-name "$stack_name" --region "$region" &>/dev/null; then
        echo "Stack $stack_name deleted successfully"
        return 0
      fi

      status=$(aws cloudformation describe-stacks --stack-name "$stack_name" --region "$region" --query "Stacks[0].StackStatus" --output text)
      if [[ $status == *FAILED* ]]; then
        echo "Stack deletion failed with status: $status"
        break
      fi

      echo "Stack deletion in progress, status: $status"
      sleep 10
    done
  done

  echo "Failed to delete stack $stack_name after $max_attempts attempts"
  return 1
}

# Function to clean up IAM roles and policies
cleanup_iam_roles_and_policies() {
  echo "Cleaning up IAM roles and policies..."

  # Get project-related roles
  echo "Finding IAM roles related to the project..."
  project_roles=$(aws iam list-roles --query "Roles[?contains(RoleName, 'BedrockChat') || contains(RoleName, 'bedrock-chat') || contains(RoleName, 'BrChat') || contains(RoleName, 'SeedcomFashion') || contains(RoleName, 'ApiPublishment')].RoleName" --output text)

  for role_name in $project_roles; do
    if [[ "$role_name" == "None" ]]; then
      continue
    fi

    echo "Processing role: $role_name"

    # Get attached policies
    attached_policies=$(aws iam list-attached-role-policies --role-name "$role_name" --query "AttachedPolicies[].PolicyArn" --output text)

    # Detach managed policies
    for policy_arn in $attached_policies; do
      if [[ "$policy_arn" != "None" ]]; then
        echo "Detaching policy $policy_arn from role $role_name"
        aws iam detach-role-policy --role-name "$role_name" --policy-arn "$policy_arn"
      fi
    done

    # Get inline policies
    inline_policies=$(aws iam list-role-policies --role-name "$role_name" --query "PolicyNames" --output text)

    # Delete inline policies
    for policy_name in $inline_policies; do
      if [[ "$policy_name" != "None" ]]; then
        echo "Deleting inline policy $policy_name from role $role_name"
        aws iam delete-role-policy --role-name "$role_name" --policy-name "$policy_name"
      fi
    done

    # Delete instance profiles associated with the role
    instance_profiles=$(aws iam list-instance-profiles-for-role --role-name "$role_name" --query "InstanceProfiles[].InstanceProfileName" --output text)
    for profile_name in $instance_profiles; do
      if [[ "$profile_name" != "None" ]]; then
        echo "Removing role from instance profile $profile_name"
        aws iam remove-role-from-instance-profile --instance-profile-name "$profile_name" --role-name "$role_name"

        echo "Deleting instance profile $profile_name"
        aws iam delete-instance-profile --instance-profile-name "$profile_name"
      fi
    done

    # Delete the role
    echo "Deleting role: $role_name"
    aws iam delete-role --role-name "$role_name"
  done

  # Get project-related customer-managed policies
  echo "Finding IAM policies related to the project..."
  project_policies=$(aws iam list-policies --scope Local --query "Policies[?contains(PolicyName, 'BedrockChat') || contains(PolicyName, 'bedrock-chat') || contains(PolicyName, 'BrChat') || contains(PolicyName, 'SeedcomFashion') || contains(PolicyName, 'ApiPublishment')].Arn" --output text)

  for policy_arn in $project_policies; do
    if [[ "$policy_arn" == "None" ]]; then
      continue
    fi

    # Delete all versions of the policy except default
    policy_versions=$(aws iam list-policy-versions --policy-arn "$policy_arn" --query "Versions[?IsDefaultVersion==\`false\`].VersionId" --output text)
    for version_id in $policy_versions; do
      if [[ "$version_id" != "None" ]]; then
        echo "Deleting policy version $version_id of policy $policy_arn"
        aws iam delete-policy-version --policy-arn "$policy_arn" --version-id "$version_id"
      fi
    done

    # Delete the policy
    echo "Deleting policy: $policy_arn"
    aws iam delete-policy --policy-arn "$policy_arn"
  done

  # Check for CDK-specific roles
  cdk_roles=$(aws iam list-roles --query "Roles[?contains(RoleName, 'cdk-') || contains(RoleName, '-role-')].RoleName" --output text)
  for role_name in $cdk_roles; do
    if [[ "$role_name" == "None" ]]; then
      continue
    fi

    # Check if role tags contain project identifiers
    tags=$(aws iam list-role-tags --role-name "$role_name" --query "Tags[?Value=='$ENV_NAME' || contains(Value, 'BedrockChat') || contains(Value, 'SeedcomFashion')]" --output text)

    if [[ -n "$tags" ]]; then
      echo "Found CDK role with project tags: $role_name"

      # Get attached policies
      attached_policies=$(aws iam list-attached-role-policies --role-name "$role_name" --query "AttachedPolicies[].PolicyArn" --output text)

      # Detach managed policies
      for policy_arn in $attached_policies; do
        if [[ "$policy_arn" != "None" ]]; then
          echo "Detaching policy $policy_arn from role $role_name"
          aws iam detach-role-policy --role-name "$role_name" --policy-arn "$policy_arn"
        fi
      done

      # Get inline policies
      inline_policies=$(aws iam list-role-policies --role-name "$role_name" --query "PolicyNames" --output text)

      # Delete inline policies
      for policy_name in $inline_policies; do
        if [[ "$policy_name" != "None" ]]; then
          echo "Deleting inline policy $policy_name from role $role_name"
          aws iam delete-role-policy --role-name "$role_name" --policy-name "$policy_name"
        fi
      done

      # Delete the role
      echo "Deleting role: $role_name"
      aws iam delete-role --role-name "$role_name"
    fi
  done
}

# Function to clean up OpenSearch domains
cleanup_opensearch_domains() {
  echo "Cleaning up OpenSearch domains..."
  for region in "$DEFAULT_REGION" "$BEDROCK_REGION"; do
    # Find all domains related to the project
    domains=$(aws opensearch list-domain-names --region "$region" --query "DomainNames[?contains(DomainName, 'bedrock') || contains(DomainName, 'kb-') || contains(DomainName, 'seedcom')].DomainName" --output text)

    for domain in $domains; do
      if [[ "$domain" == "None" ]]; then
        continue
      fi

      echo "Deleting OpenSearch domain: $domain in region $region"
      aws opensearch delete-domain --domain-name "$domain" --region "$region"
    done
  done

  # Clean OpenSearchServerless collections
  echo "Cleaning up OpenSearchServerless collections..."
  for region in "$DEFAULT_REGION" "$BEDROCK_REGION"; do
    collections=$(aws opensearchserverless list-collections --region "$region" --query "collectionSummaries[?contains(name, 'kb-') || contains(name, 'bedrock') || contains(name, 'seedcom')].id" --output text)

    for collection_id in $collections; do
      if [[ "$collection_id" == "None" ]]; then
        continue
      fi

      echo "Deleting OpenSearchServerless collection: $collection_id in region $region"
      aws opensearchserverless delete-collection --id "$collection_id" --region "$region"

      # Wait for collection to be deleted
      while true; do
        status=$(aws opensearchserverless batch-get-collection --ids "$collection_id" --region "$region" --query "collectionDetails[0].status" --output text 2>/dev/null || echo "DELETED")

        if [[ "$status" == "DELETED" || "$status" == "None" ]]; then
          echo "Collection $collection_id deleted successfully"
          break
        fi

        echo "Collection deletion in progress, status: $status"
        sleep 10
      done
    done
  done
}

# Function to clean up API Gateway resources
cleanup_api_gateway() {
  echo "Cleaning up API Gateway resources..."

  for region in "$DEFAULT_REGION" "$BEDROCK_REGION"; do
    # Clean up REST APIs
    rest_apis=$(aws apigateway get-rest-apis --region "$region" --query "items[?contains(name, 'BedrockChat') || contains(name, 'bedrock-chat') || contains(name, 'ApiPublishment')].id" --output text)

    for api_id in $rest_apis; do
      if [[ "$api_id" == "None" ]]; then
        continue
      fi

      echo "Deleting REST API: $api_id in region $region"
      aws apigateway delete-rest-api --rest-api-id "$api_id" --region "$region"
    done

    # Clean up HTTP APIs
    http_apis=$(aws apigatewayv2 get-apis --region "$region" --query "Items[?contains(Name, 'BedrockChat') || contains(Name, 'bedrock-chat') || contains(Name, 'ApiPublishment')].ApiId" --output text)

    for api_id in $http_apis; do
      if [[ "$api_id" == "None" ]]; then
        continue
      fi

      echo "Deleting HTTP API: $api_id in region $region"
      aws apigatewayv2 delete-api --api-id "$api_id" --region "$region"
    done
  done
}

# Function to clean up CloudFront distributions
cleanup_cloudfront() {
  echo "Cleaning up CloudFront distributions..."

  # Get all CloudFront distributions
  distributions=$(aws cloudfront list-distributions --query "DistributionList.Items[?contains(Origins.Items[0].DomainName, 'bedrock') || contains(Origins.Items[0].DomainName, 'seedcom') || contains(Comment, 'BedrockChat') || contains(Comment, 'SeedcomFashion')].Id" --output text)

  for dist_id in $distributions; do
    if [[ "$dist_id" == "None" ]]; then
      continue
    fi

    # Get current config to check if it's disabled
    etag=$(aws cloudfront get-distribution-config --id "$dist_id" --query "ETag" --output text)
    enabled=$(aws cloudfront get-distribution-config --id "$dist_id" --query "DistributionConfig.Enabled" --output text)

    if [[ "$enabled" == "true" ]]; then
      echo "Disabling CloudFront distribution: $dist_id"
      # We need to disable the distribution before deleting it
      aws cloudfront update-distribution --id "$dist_id" --if-match "$etag" --distribution-config "{\"CallerReference\":\"$dist_id\",\"Enabled\":false}"

      # Wait until the distribution is fully deployed with the disabled status
      while true; do
        status=$(aws cloudfront get-distribution --id "$dist_id" --query "Distribution.Status" --output text)
        if [[ "$status" == "Deployed" ]]; then
          break
        fi
        echo "Waiting for distribution to be deployed with disabled status, current status: $status"
        sleep 30
      done

      # Get new etag
      etag=$(aws cloudfront get-distribution-config --id "$dist_id" --query "ETag" --output text)
    fi

    echo "Deleting CloudFront distribution: $dist_id"
    aws cloudfront delete-distribution --id "$dist_id" --if-match "$etag"
  done
}

# Function to clean up ECR repositories
cleanup_ecr() {
  echo "Cleaning up ECR repositories..."

  # List repositories
  repos=$(aws ecr describe-repositories --query "repositories[?contains(repositoryName, 'bedrock') || contains(repositoryName, 'seedcom')].repositoryName" --output text)

  for repo in $repos; do
    if [[ "$repo" == "None" ]]; then
      continue
    fi

    echo "Deleting ECR repository: $repo"
    aws ecr delete-repository --repository-name "$repo" --force
  done
}

# Function to clean up KMS keys
cleanup_kms_keys() {
  echo "Cleaning up KMS keys..."

  for region in "$DEFAULT_REGION" "$BEDROCK_REGION"; do
    # List keys with aliases related to our project
    aliases=$(aws kms list-aliases --region "$region" --query "Aliases[?contains(AliasName, 'bedrock') || contains(AliasName, 'seedcom')].TargetKeyId" --output text)

    for key_id in $aliases; do
      if [[ "$key_id" == "None" ]]; then
        continue
      fi

      echo "Scheduling deletion of KMS key: $key_id in region $region"
      aws kms schedule-key-deletion --key-id "$key_id" --pending-window-in-days 7 --region "$region"
    done
  done
}

# Function to clean up SNS topics
cleanup_sns_topics() {
  echo "Cleaning up SNS topics..."

  for region in "$DEFAULT_REGION" "$BEDROCK_REGION"; do
    # List topics related to our project
    topics=$(aws sns list-topics --region "$region" --query "Topics[?contains(TopicArn, 'BedrockChat') || contains(TopicArn, 'bedrock-chat') || contains(TopicArn, 'SeedcomFashion')].TopicArn" --output text)

    for topic_arn in $topics; do
      if [[ "$topic_arn" == "None" ]]; then
        continue
      fi

      echo "Deleting SNS topic: $topic_arn in region $region"
      aws sns delete-topic --topic-arn "$topic_arn" --region "$region"
    done
  done
}

# Function to clean up SQS queues
cleanup_sqs_queues() {
  echo "Cleaning up SQS queues..."

  for region in "$DEFAULT_REGION" "$BEDROCK_REGION"; do
    # List queues related to our project - limited search due to SQS URL format
    queue_urls=$(aws sqs list-queues --region "$region" --queue-name-prefix "bedrock" --query "QueueUrls[]" --output text)

    for queue_url in $queue_urls; do
      if [[ "$queue_url" == "None" ]]; then
        continue
      fi

      echo "Deleting SQS queue: $queue_url in region $region"
      aws sqs delete-queue --queue-url "$queue_url" --region "$region"
    done

    # List queues with seedcom prefix
    queue_urls=$(aws sqs list-queues --region "$region" --queue-name-prefix "seedcom" --query "QueueUrls[]" --output text)

    for queue_url in $queue_urls; do
      if [[ "$queue_url" == "None" ]]; then
        continue
      fi

      echo "Deleting SQS queue: $queue_url in region $region"
      aws sqs delete-queue --queue-url "$queue_url" --region "$region"
    done
  done
}

# Function to clean up Cognito User Pools
cleanup_cognito() {
  echo "Cleaning up Cognito User Pools..."

  for region in "$DEFAULT_REGION" "$BEDROCK_REGION"; do
    # List user pools related to our project
    user_pools=$(aws cognito-idp list-user-pools --max-results 60 --region "$region" --query "UserPools[?contains(Name, 'BedrockChat') || contains(Name, 'bedrock-chat') || contains(Name, 'SeedcomFashion')].Id" --output text)

    for pool_id in $user_pools; do
      if [[ "$pool_id" == "None" ]]; then
        continue
      fi

      echo "Deleting Cognito User Pool: $pool_id in region $region"
      aws cognito-idp delete-user-pool --user-pool-id "$pool_id" --region "$region"
    done
  done
}

# Function to clean up WAF WebACLs
cleanup_waf() {
  echo "Cleaning up WAF WebACLs..."

  for region in "$DEFAULT_REGION" "us-east-1"; do  # WAF for CloudFront is always in us-east-1
    # List v2 Web ACLs
    web_acls=$(aws wafv2 list-web-acls --scope CLOUDFRONT --region "$region" --query "WebACLs[?contains(Name, 'BedrockChat') || contains(Name, 'bedrock-chat') || contains(Name, 'SeedcomFashion')].{Name:Name,Id:Id}" --output json 2>/dev/null || echo "[]")

    echo "$web_acls" | jq -c '.[]' 2>/dev/null | while read -r acl; do
      if [[ "$acl" == "null" || "$acl" == "" ]]; then
        continue
      fi

      acl_id=$(echo "$acl" | jq -r '.Id')
      acl_name=$(echo "$acl" | jq -r '.Name')

      # Get resource associations
      resources=$(aws wafv2 list-resources-for-web-acl --web-acl-arn "arn:aws:wafv2:$region:$ACCOUNT_ID:global/webacl/$acl_name/$acl_id" --resource-type CLOUDFRONT --region "$region" --query "ResourceArns[]" --output text)

      # Disassociate resources
      for resource in $resources; do
        if [[ "$resource" == "None" ]]; then
          continue
        fi

        echo "Disassociating WAF WebACL from resource: $resource"
        aws wafv2 disassociate-web-acl --resource-arn "$resource" --region "$region"
      done

      echo "Deleting WAF WebACL: $acl_name ($acl_id) in region $region"
      aws wafv2 delete-web-acl --name "$acl_name" --id "$acl_id" --scope CLOUDFRONT --region "$region"
    done

    # List classic Web ACLs if they exist
    classic_web_acls=$(aws waf list-web-acls --region "$region" --query "WebACLs[?contains(Name, 'BedrockChat') || contains(Name, 'bedrock-chat')].{Name:Name,WebACLId:WebACLId}" --output json 2>/dev/null || echo "[]")

    echo "$classic_web_acls" | jq -c '.[]' 2>/dev/null | while read -r acl; do
      if [[ "$acl" == "null" || "$acl" == "" ]]; then
        continue
      fi

      acl_id=$(echo "$acl" | jq -r '.WebACLId')

      echo "Deleting classic WAF WebACL: $acl_id in region $region"
      aws waf delete-web-acl --web-acl-id "$acl_id" --region "$region"
    done
  done
}

# Function to clean up EventBridge rules
cleanup_eventbridge() {
  echo "Cleaning up EventBridge rules..."

  for region in "$DEFAULT_REGION" "$BEDROCK_REGION"; do
    # List rules related to our project
    rules=$(aws events list-rules --region "$region" --query "Rules[?contains(Name, 'BedrockChat') || contains(Name, 'bedrock-chat') || contains(Name, 'SeedcomFashion')].Name" --output text)

    for rule_name in $rules; do
      if [[ "$rule_name" == "None" ]]; then
        continue
      fi

      # Remove targets from rule
      targets=$(aws events list-targets-by-rule --rule "$rule_name" --region "$region" --query "Targets[].Id" --output text)
      if [[ -n "$targets" && "$targets" != "None" ]]; then
        echo "Removing targets from rule: $rule_name in region $region"
        aws events remove-targets --rule "$rule_name" --ids $targets --region "$region"
      fi

      echo "Deleting EventBridge rule: $rule_name in region $region"
      aws events delete-rule --name "$rule_name" --region "$region"
    done
  done
}

# Function to clean up Bedrock Knowledge Base resources
cleanup_bedrock_kb() {
  echo "Cleaning up Bedrock Knowledge Base resources..."

  for region in "$DEFAULT_REGION" "$BEDROCK_REGION"; do
    # List knowledge bases
    kbs=$(aws bedrock-agent list-knowledge-bases --region "$region" --query "knowledgeBaseSummaries[?contains(name, 'SeedcomFashion') || contains(name, 'kb-')].knowledgeBaseId" --output text 2>/dev/null || echo "")

    for kb_id in $kbs; do
      if [[ "$kb_id" == "None" || -z "$kb_id" ]]; then
        continue
      fi

      # Delete data sources first
      datasources=$(aws bedrock-agent list-data-sources --knowledge-base-id "$kb_id" --region "$region" --query "dataSourceSummaries[].dataSourceId" --output text 2>/dev/null || echo "")
      for ds_id in $datasources; do
        if [[ "$ds_id" == "None" || -z "$ds_id" ]]; then
          continue
        fi
        echo "Deleting Bedrock data source: $ds_id from knowledge base $kb_id in region $region"
        aws bedrock-agent delete-data-source --knowledge-base-id "$kb_id" --data-source-id "$ds_id" --region "$region"
      done

      echo "Deleting Bedrock Knowledge Base: $kb_id in region $region"
      aws bedrock-agent delete-knowledge-base --knowledge-base-id "$kb_id" --region "$region"
    done

    # List guardrails
    guardrails=$(aws bedrock list-guardrails --region "$region" --query "guardrails[?contains(name, 'BrChatGuardrail-')].guardrailId" --output text 2>/dev/null || echo "")

    for guardrail_id in $guardrails; do
      if [[ "$guardrail_id" == "None" || -z "$guardrail_id" ]]; then
        continue
      fi

      echo "Deleting Bedrock Guardrail: $guardrail_id in region $region"
      aws bedrock delete-guardrail --guardrail-identifier "$guardrail_id" --region "$region"
    done
  done
}

# Step 1: Delete all custom bots and API publication stacks
echo "=== Step 1: Deleting all custom bot stacks ==="
for region in "$DEFAULT_REGION" "$BEDROCK_REGION"; do
  echo "Searching for bot stacks in region: $region"

  # Find all stacks related to the project
  bot_stacks=$(aws cloudformation list-stacks --region "$region" --query "StackSummaries[?contains(StackName, 'SeedcomFashion') || contains(StackName, 'BrChatKbStack') || contains(StackName, 'ApiPublishmentStack')].StackName" --output text)

  for stack in $bot_stacks; do
    if [[ $stack != "None" ]]; then
      delete_stack "$stack" "$region"
    fi
  done
done

# Step 2: Clean up Bedrock Knowledge Base resources
echo "=== Step 2: Cleaning up Bedrock Knowledge Base resources ==="
cleanup_bedrock_kb

# Step 3: Delete main stacks in reverse order of dependencies
echo "=== Step 3: Deleting main project stacks ==="

# Delete Bedrock Chat Stack
delete_stack "${STACK_PREFIX}BedrockChatStack" "$DEFAULT_REGION"

# Delete Bedrock Region Resources Stack
delete_stack "${STACK_PREFIX}BedrockRegionResourcesStack" "$BEDROCK_REGION"

# Delete Frontend WAF Stack (always in us-east-1)
delete_stack "${STACK_PREFIX}FrontendWafStack" "us-east-1"

# Step 4: Clean up OpenSearch domains and collections
echo "=== Step 4: Cleaning up OpenSearch resources ==="
cleanup_opensearch_domains

# Step 5: Clean up API Gateway resources
echo "=== Step 5: Cleaning up API Gateway resources ==="
cleanup_api_gateway

# Step 6: Clean up CloudFront distributions
echo "=== Step 6: Cleaning up CloudFront distributions ==="
cleanup_cloudfront

# Step 7: Clean up S3 buckets
echo "=== Step 7: Cleaning up S3 buckets ==="

# Find all S3 buckets related to the project
echo "Finding all S3 buckets related to the project..."
related_buckets=$(aws s3api list-buckets --query "Buckets[?contains(Name, 'bedrock') || contains(Name, 'cloudformation') || contains(Name, 'cdk')].Name" --output text)

for bucket in $related_buckets; do
  if [[ "$bucket" == "None" ]]; then
    continue
  fi

  # Skip system buckets
  if [[ "$bucket" == *"-assets-"* ]] || [[ "$bucket" == "cf-templates-"* ]]; then
    echo "Skipping system bucket: $bucket"
    continue
  fi

  # Check if bucket belongs to our project
  # This is a heuristic - we check if the bucket contains our environment name or specific project identifiers
  if [[ "$bucket" == *"bedrock-chat"* ]] || [[ "$bucket" == *"$ENV_NAME"* ]] || [[ "$bucket" == *"seedcom"* ]]; then
    empty_and_delete_bucket "$bucket"
  fi
done

# Step 8: Clean up other resources
echo "=== Step 8: Cleaning up other resources ==="

# Find and delete any remaining Lambda functions
echo "Deleting Lambda functions..."
for region in "$DEFAULT_REGION" "$BEDROCK_REGION"; do
  lambda_functions=$(aws lambda list-functions --region "$region" --query "Functions[?contains(FunctionName, 'BedrockChat') || contains(FunctionName, 'bedrock-chat') || contains(FunctionName, 'SeedcomFashion')].FunctionName" --output text)
  for func in $lambda_functions; do
    if [[ "$func" != "None" ]]; then
      echo "Deleting Lambda function: $func in region $region"
      aws lambda delete-function --function-name "$func" --region "$region"
    fi
  done
done

# Clean up DynamoDB tables
echo "Deleting DynamoDB tables..."
tables=$(aws dynamodb list-tables --region "$DEFAULT_REGION" --query "TableNames[?contains(@, 'BedrockChat') || contains(@, 'bedrock-chat') || contains(@, 'SeedcomFashion')]" --output text)
for table in $tables; do
  if [[ "$table" != "None" ]]; then
    echo "Deleting DynamoDB table: $table"
    aws dynamodb delete-table --table-name "$table" --region "$DEFAULT_REGION"
  fi
done

# Clean up CloudWatch log groups
echo "Deleting CloudWatch log groups..."
for region in "$DEFAULT_REGION" "$BEDROCK_REGION" "us-east-1"; do
  log_groups=$(aws logs describe-log-groups --region "$region" --query "logGroups[?contains(logGroupName, '/aws/lambda/BedrockChat') || contains(logGroupName, '/aws/lambda/bedrock-chat') || contains(logGroupName, '/aws/codebuild/') || contains(logGroupName, 'SeedcomFashion')].logGroupName" --output text)
  for log_group in $log_groups; do
    if [[ "$log_group" != "None" ]]; then
      echo "Deleting log group: $log_group in region $region"
      aws logs delete-log-group --log-group-name "$log_group" --region "$region"
    fi
  done
done

# Clean up SQS queues
echo "=== Step 9: Cleaning up SQS queues ==="
cleanup_sqs_queues

# Clean up SNS topics
echo "=== Step 10: Cleaning up SNS topics ==="
cleanup_sns_topics

# Clean up EventBridge rules
echo "=== Step 11: Cleaning up EventBridge rules ==="
cleanup_eventbridge

# Clean up Cognito User Pools
echo "=== Step 12: Cleaning up Cognito User Pools ==="
cleanup_cognito

# Clean up WAF WebACLs
echo "=== Step 13: Cleaning up WAF WebACLs ==="
cleanup_waf

# Clean up ECR repositories
echo "=== Step 14: Cleaning up ECR repositories ==="
cleanup_ecr

# Clean up KMS keys
echo "=== Step 15: Cleaning up KMS keys ==="
cleanup_kms_keys

# Clean up IAM roles and policies
echo "=== Step 16: Cleaning up IAM roles and policies ==="
cleanup_iam_roles_and_policies

# Clean up CDK bootstrap resources if desired
echo "=== Step 17: CDK Bootstrap Resources ==="
echo "Do you want to remove CDK bootstrap resources? (y/N)"
read -r remove_bootstrap

if [[ "$remove_bootstrap" == "y" || "$remove_bootstrap" == "Y" ]]; then
  echo "Removing CDK bootstrap stack..."
  delete_stack "CDKToolkit" "$DEFAULT_REGION"
  delete_stack "CDKToolkit" "$BEDROCK_REGION"

  cdk_bucket_default=$(aws s3api list-buckets --query "Buckets[?contains(Name, 'cdk-hnb659fds-assets-$ACCOUNT_ID-$DEFAULT_REGION')].Name" --output text)
  cdk_bucket_bedrock=$(aws s3api list-buckets --query "Buckets[?contains(Name, 'cdk-hnb659fds-assets-$ACCOUNT_ID-$BEDROCK_REGION')].Name" --output text)

  if [[ "$cdk_bucket_default" != "None" ]]; then
    empty_and_delete_bucket "$cdk_bucket_default"
  fi

  if [[ "$cdk_bucket_bedrock" != "None" ]]; then
    empty_and_delete_bucket "$cdk_bucket_bedrock"
  fi
else
  echo "Skipping CDK bootstrap resource cleanup"
fi

echo "==================================================="
echo "Cleanup completed!"
echo "==================================================="
echo ""
echo "Note: Some resources may still exist if they were:"
echo "1. Protected against deletion"
echo "2. Created outside the CloudFormation stacks"
echo "3. In other regions not specified in this script"
echo ""
echo "Please check the AWS Console to verify all resources"
echo "have been properly deleted."