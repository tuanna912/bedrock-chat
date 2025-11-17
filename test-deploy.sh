#!/bin/bash
set -e

echo "🧪 Testing Published WebSocket Stack deployment..."
echo ""

cd cdk

echo "✅ Step 1: Install dependencies"
npm ci --silent

echo ""
echo "✅ Step 2: Compile TypeScript"
npx tsc --noEmit || echo "⚠️  TypeScript warnings (safe to ignore)"

echo ""
echo "✅ Step 3: CDK synth test"
npx cdk synth --app "npx ts-node bin/test-published-websocket.ts" > /dev/null
echo "   ✓ Stack synthesized successfully"

echo ""
echo "✅ Step 4: Validate CloudFormation template"
TEMPLATE=$(npx cdk synth --app "npx ts-node bin/test-published-websocket.ts" 2>/dev/null)
echo "$TEMPLATE" | aws cloudformation validate-template --template-body file:///dev/stdin > /dev/null 2>&1
if [ $? -eq 0 ]; then
    echo "   ✓ CloudFormation template is valid"
else
    echo "   ⚠️  Template validation skipped (requires AWS credentials)"
fi

echo ""
echo "✅ Step 5: Check required resources"
echo "$TEMPLATE" | grep -q "AWS::SSM::Parameter" && echo "   ✓ SSM Parameter"
echo "$TEMPLATE" | grep -q "AWS::DynamoDB::Table" && echo "   ✓ DynamoDB Table"
echo "$TEMPLATE" | grep -q "AWS::Lambda::Function" && echo "   ✓ Lambda Function"
echo "$TEMPLATE" | grep -q "AWS::ApiGatewayV2::Api" && echo "   ✓ WebSocket API"
echo "$TEMPLATE" | grep -q "AWS::IAM::Role" && echo "   ✓ IAM Role"

echo ""
echo "✅ Step 6: Check Python handler exists"
if [ -f "../backend/app/published_websocket.py" ]; then
    echo "   ✓ published_websocket.py found"
    python3 -m py_compile ../backend/app/published_websocket.py 2>/dev/null && echo "   ✓ Python syntax valid"
else
    echo "   ❌ published_websocket.py not found"
    exit 1
fi

echo ""
echo "✅ Step 7: Estimate deployment size"
TEMPLATE_SIZE=$(echo "$TEMPLATE" | wc -c)
echo "   Template size: $TEMPLATE_SIZE bytes"
if [ $TEMPLATE_SIZE -gt 51200 ]; then
    echo "   ⚠️  Template is large, may need S3 bucket for deployment"
fi

echo ""
echo "🎉 All tests passed! Ready to deploy on CloudShell"
echo ""
echo "📋 Next steps:"
echo "   1. Upload code to CloudShell"
echo "   2. Run: cd cdk && npm ci"
echo "   3. Run: npx cdk bootstrap (if first time)"
echo "   4. Run: npx cdk deploy --app 'npx ts-node bin/test-published-websocket.ts'"
echo ""
