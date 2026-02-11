# Deploy Published WebSocket trên CloudShell

## ⚡ Cách 1: Deploy qua CodeBuild (Khuyến nghị - Tránh lỗi storage)

```bash
# Trên CloudShell, clone repo
git clone https://github.com/tuanna912/bedrock-chat.git
cd bedrock-chat
git checkout feature/no-authen-chatbot

# Deploy với script tự động
chmod +x deploy-published-websocket.sh
./deploy-published-websocket.sh ask-bot tvZvFpHxVb5WqLUOPfEOd63rWNRanRgF612GwafS us-east-1
```

**Parameters:**
- `ask-bot`: Bot ID
- `tvZvFpHxVb5WqLUOPfEOd63rWNRanRgF612GwafS`: API Key
- `us-east-1`: AWS Region

## 🔧 Cách 2: Deploy thủ công (Nếu có đủ storage)

### Bước 1: Tạo SSM Parameter

```bash
aws ssm put-parameter \
  --name "/bedrock-chat/published-bot/ask-bot/api-key" \
  --value "tvZvFpHxVb5WqLUOPfEOd63rWNRanRgF612GwafS" \
  --type "String" \
  --description "API key for published bot ask-bot" \
  --region us-east-1
```

### Bước 2: Deploy CDK Stack

```bash
cd cdk

# Install dependencies
npm ci

# Bootstrap (nếu chưa làm)
npx cdk bootstrap

# Deploy test stack
npx cdk deploy --app "npx ts-node bin/test-published-websocket.ts" --require-approval never
```

## Bước 4: Lấy WebSocket Endpoint

```bash
aws cloudformation describe-stacks \
  --stack-name TestPublishedWS \
  --query 'Stacks[0].Outputs[?OutputKey==`WebSocketEndpoint`].OutputValue' \
  --output text \
  --region us-east-1
```

## Bước 5: Test WebSocket

Sử dụng endpoint và API key để test với HTML client hoặc Python script.

## Troubleshooting

### Nếu gặp lỗi "No space left on device"
```bash
# Dọn dẹp Docker images
docker system prune -af
```

### Nếu gặp lỗi IAM permissions
```bash
# Kiểm tra CloudShell có đủ quyền
aws sts get-caller-identity
```

### Xem logs nếu có lỗi
```bash
# Lambda logs
aws logs tail /aws/lambda/TestPublishedWS-Handler --follow

# CloudFormation events
aws cloudformation describe-stack-events --stack-name TestPublishedWS --max-items 10
```

## Clean up

```bash
# Xóa stack khi không dùng nữa
npx cdk destroy TestPublishedWS --app "npx ts-node bin/test-published-websocket.ts"

# Xóa SSM parameter
aws ssm delete-parameter --name "/bedrock-chat/published-bot/ask-bot/api-key"
```
