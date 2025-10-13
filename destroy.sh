#!/bin/bash

echo "==========================================================================="
echo "  ⚠️  WARNING: This will DELETE ALL Bedrock Chat resources!"
echo "==========================================================================="
echo "  This script will permanently delete:"
echo "  - All conversations and chat history"
echo "  - All custom bots and knowledge bases"
echo "  - All user data"
echo "  - All CloudFormation stacks"
echo ""
echo "  This action CANNOT be undone!"
echo "==========================================================================="
echo ""

read -p "Are you absolutely sure you want to destroy everything? Type 'DELETE' to confirm: " confirm
if [ "$confirm" != "DELETE" ]; then
    echo "Destruction cancelled."
    exit 0
fi

echo ""
echo "Starting destruction process..."
echo ""

# Function to wait for stack deletion
wait_for_deletion() {
    local stack_name=$1
    echo "Waiting for $stack_name to be deleted..."
    while true; do
        status=$(aws cloudformation describe-stacks --stack-name "$stack_name" --query 'Stacks[0].StackStatus' --output text 2>/dev/null)
        if [ $? -ne 0 ]; then
            echo "✓ $stack_name deleted"
            break
        fi
        if [[ "$status" == "DELETE_FAILED" ]]; then
            echo "✗ $stack_name deletion failed"
            break
        fi
        sleep 5
    done
}

# Step 1: Delete API Publication stacks
echo "Step 1: Deleting API Publication stacks..."
api_stacks=$(aws cloudformation list-stacks --stack-status-filter CREATE_COMPLETE UPDATE_COMPLETE --query 'StackSummaries[?starts_with(StackName, `ApiPublishmentStack`)].StackName' --output text)
for stack in $api_stacks; do
    echo "  Deleting $stack..."
    aws cloudformation delete-stack --stack-name "$stack"
done
for stack in $api_stacks; do
    wait_for_deletion "$stack"
done

# Step 2: Delete Custom Bot KB stacks
echo ""
echo "Step 2: Deleting Custom Bot Knowledge Base stacks..."
kb_stacks=$(aws cloudformation list-stacks --stack-status-filter CREATE_COMPLETE UPDATE_COMPLETE --query 'StackSummaries[?starts_with(StackName, `BrChatKbStack`)].StackName' --output text)
for stack in $kb_stacks; do
    echo "  Deleting $stack..."
    aws cloudformation delete-stack --stack-name "$stack"
done
for stack in $kb_stacks; do
    wait_for_deletion "$stack"
done

# Step 3: Delete KnowledgeBase Quick Create stacks
echo ""
echo "Step 3: Deleting KnowledgeBase Quick Create stacks..."
quick_kb_stacks=$(aws cloudformation list-stacks --stack-status-filter CREATE_COMPLETE UPDATE_COMPLETE --query 'StackSummaries[?starts_with(StackName, `KnowledgeBaseQuickCreateAurora`)].StackName' --output text)
for stack in $quick_kb_stacks; do
    echo "  Deleting $stack..."
    aws cloudformation delete-stack --stack-name "$stack"
done
for stack in $quick_kb_stacks; do
    wait_for_deletion "$stack"
done

# Step 4: Delete BedrockChatStack
echo ""
echo "Step 4: Deleting BedrockChatStack..."
if aws cloudformation describe-stacks --stack-name BedrockChatStack >/dev/null 2>&1; then
    aws cloudformation delete-stack --stack-name BedrockChatStack
    wait_for_deletion "BedrockChatStack"
fi

# Step 5: Delete BedrockRegionResourcesStack
echo ""
echo "Step 5: Deleting BedrockRegionResourcesStack..."
if aws cloudformation describe-stacks --stack-name BedrockRegionResourcesStack >/dev/null 2>&1; then
    aws cloudformation delete-stack --stack-name BedrockRegionResourcesStack
    wait_for_deletion "BedrockRegionResourcesStack"
fi

# Step 6: Delete FrontendWafStack (in us-east-1)
echo ""
echo "Step 6: Deleting FrontendWafStack (us-east-1)..."
if aws cloudformation describe-stacks --stack-name FrontendWafStack --region us-east-1 >/dev/null 2>&1; then
    aws cloudformation delete-stack --stack-name FrontendWafStack --region us-east-1
    wait_for_deletion "FrontendWafStack"
fi

# Step 7: Delete CodeBuildForDeploy stack
echo ""
echo "Step 7: Deleting CodeBuildForDeploy stack..."
if aws cloudformation describe-stacks --stack-name CodeBuildForDeploy >/dev/null 2>&1; then
    aws cloudformation delete-stack --stack-name CodeBuildForDeploy
    wait_for_deletion "CodeBuildForDeploy"
fi

# Step 8: Delete CDK Bootstrap stack (optional)
echo ""
read -p "Do you want to delete CDK Bootstrap stack? (y/N): " delete_bootstrap
if [[ "$delete_bootstrap" =~ ^[Yy]$ ]]; then
    echo "Deleting CDKToolkit stack..."
    if aws cloudformation describe-stacks --stack-name CDKToolkit >/dev/null 2>&1; then
        aws cloudformation delete-stack --stack-name CDKToolkit
        wait_for_deletion "CDKToolkit"
    fi
fi

echo ""
echo "==========================================================================="
echo "  ✓ Destruction complete!"
echo "==========================================================================="
echo ""
echo "All Bedrock Chat resources have been deleted."
echo ""
