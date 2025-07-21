#!/bin/bash
echo ""
echo "==========================================================================="
echo "  Frontend Only Deployment Script                                          "
echo "---------------------------------------------------------------------------"
echo "  This script will only deploy the frontend part of the application.       "
echo "  Backend resources will not be affected.                                  "
echo "==========================================================================="
echo ""

while true; do
    read -p "Do you want to proceed with frontend-only deployment? (y/N): " answer
    case ${answer:0:1} in
        y|Y )
            echo "Starting frontend-only deployment..."
            break
            ;;
        n|N )
            echo "Deployment cancelled."
            exit 1
            ;;
        * )
            echo "Please enter y or n."
            ;;
    esac
done

# Default parameters
REPO_URL="https://github.com/tuanna912/bedrock-chat.git"
VERSION="develop"
CDK_JSON_OVERRIDE="{\"deploy\": \"frontend-only\"}"

# Parse command-line arguments for customization
while [[ "$#" -gt 0 ]]; do
    case $1 in
        --repo-url) REPO_URL="$2"; shift ;;
        --version) VERSION="$2"; shift ;;
        --cdk-json-override) CDK_JSON_OVERRIDE="$2"; shift ;;
        *) echo "Unknown parameter: $1"; exit 1 ;;
    esac
    shift
done

# Validate the template
aws cloudformation validate-template --template-body file://deploy.yml  > /dev/null 2>&1
if [[ $? -ne 0 ]]; then
    echo "Template validation failed"
    exit 1
fi

StackName="CodeBuildForFrontendDeploy"

# Deploy the CloudFormation stack with frontend-only flag
aws cloudformation deploy \
  --stack-name $StackName \
  --template-file deploy.yml \
  --capabilities CAPABILITY_IAM \
  --parameter-overrides \
    CdkJsonOverride="$CDK_JSON_OVERRIDE" \
    RepoUrl="$REPO_URL" \
    Version="$VERSION" \
    FrontendOnly="true"

echo "Waiting for the stack creation to complete..."
echo "NOTE: this stack contains CodeBuild project which will be used for frontend-only deploy."
spin='-\|/'
i=0
while true; do
    status=$(aws cloudformation describe-stacks --stack-name $StackName --query 'Stacks[0].StackStatus' --output text 2>/dev/null)
    if [[ "$status" == "CREATE_COMPLETE" || "$status" == "UPDATE_COMPLETE" || "$status" == "DELETE_COMPLETE" ]]; then
        break
    elif [[ "$status" == "ROLLBACK_COMPLETE" || "$status" == "DELETE_FAILED" || "$status" == "CREATE_FAILED" ]]; then
        echo "Stack creation failed with status: $status"
        exit 1
    fi
    printf "\r${spin:i++%${#spin}:1}"
    sleep 1
done
echo -e "\nDone.\n"

outputs=$(aws cloudformation describe-stacks --stack-name $StackName --query 'Stacks[0].Outputs')
projectName=$(echo $outputs | jq -r '.[] | select(.OutputKey=="ProjectName").OutputValue')

if [[ -z "$projectName" ]]; then
    echo "Failed to retrieve the CodeBuild project name"
    exit 1
fi

echo "Starting CodeBuild project: $projectName for frontend-only deployment..."
buildId=$(aws codebuild start-build --project-name $projectName --query 'build.id' --output text --environment-variables-override name=FRONTEND_ONLY,value=true,type=PLAINTEXT)

if [[ -z "$buildId" ]]; then
    echo "Failed to start CodeBuild project"
    exit 1
fi

echo "Waiting for the frontend deployment to complete..."
while true; do
    buildStatus=$(aws codebuild batch-get-builds --ids $buildId --query 'builds[0].buildStatus' --output text)
    if [[ "$buildStatus" == "SUCCEEDED" || "$buildStatus" == "FAILED" || "$buildStatus" == "STOPPED" ]]; then
        break
    fi
    sleep 10
done
echo "Frontend deployment completed with status: $buildStatus"

buildDetail=$(aws codebuild batch-get-builds --ids $buildId --query 'builds[0].logs.{groupName: groupName, streamName: streamName}' --output json)

logGroupName=$(echo $buildDetail | jq -r '.groupName')
logStreamName=$(echo $buildDetail | jq -r '.streamName')

echo "Build Log Group Name: $logGroupName"
echo "Build Log Stream Name: $logStreamName"

echo "Fetch frontend deployment logs..."
logs=$(aws logs get-log-events --log-group-name $logGroupName --log-stream-name $logStreamName)
frontendUrl=$(echo "$logs" | grep -o 'FrontendURL = [^ ]*' | cut -d' ' -f3 | tr -d '\n,')

echo "Frontend URL: $frontendUrl"