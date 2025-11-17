# Published WebSocket API - Quick Start

Deploy chatbot WebSocket API công khai với API Key authentication (không cần Cognito login).

## ⚠️ Yêu cầu

**Phải deploy BedrockChatStack trước:**
```bash
./bin.sh
```

## 🚀 Deploy nhanh trên CloudShell

```bash
# Clone repo
git clone https://github.com/tuanna912/bedrock-chat.git
cd bedrock-chat
git checkout feature/no-authen-chatbot

# Deploy qua CodeBuild (tránh lỗi storage)
chmod +x deploy-published-websocket.sh
./deploy-published-websocket.sh ask-bot tvZvFpHxVb5WqLUOPfEOd63rWNRanRgF612GwafS us-east-1
```

## 💻 Deploy local (nếu có đủ storage)

```bash
# Trong thư mục bedrock-chat
chmod +x test-published-websocket-local.sh
./test-published-websocket-local.sh ask-bot tvZvFpHxVb5WqLUOPfEOd63rWNRanRgF612GwafS us-east-1
```

**Kết quả:**
- ✅ Tạo SSM Parameter với API Key
- ✅ Deploy WebSocket API qua CodeBuild (tránh lỗi storage)
- ✅ Nhận WebSocket endpoint để test

## 🧪 Test

### HTML Client (Dễ nhất)
```bash
open examples/published-websocket-client.html
```
Nhập WebSocket endpoint và API key vào form.

### Python Script
```bash
pip install websockets
# Sửa WS_ENDPOINT trong file
python3 examples/test_published_websocket.py
```

## 📋 Lấy thông tin

```bash
# WebSocket Endpoint
aws cloudformation describe-stacks \
  --stack-name PublishedWS-ask-bot \
  --query 'Stacks[0].Outputs[?OutputKey==`WebSocketEndpoint`].OutputValue' \
  --output text

# API Key
aws ssm get-parameter \
  --name "/bedrock-chat/published-bot/ask-bot/api-key" \
  --query 'Parameter.Value' \
  --output text
```

## 🔧 Troubleshooting

### Lỗi "No space left on device"
✅ Script tự động dùng CodeBuild, không cần storage local

### Xem logs
```bash
# Lambda logs
aws logs tail /aws/lambda/PublishedWS-ask-bot-Handler --follow

# CodeBuild logs
aws codebuild list-builds-for-project --project-name <PROJECT_NAME>
```

## 🗑️ Clean up

```bash
# Xóa stack
aws cloudformation delete-stack --stack-name PublishedWS-ask-bot
aws cloudformation delete-stack --stack-name PublishedWSCodeBuild-ask-bot

# Xóa SSM parameter
aws ssm delete-parameter --name "/bedrock-chat/published-bot/ask-bot/api-key"
```

## 🔒 Bảo mật

- ✅ API Key authentication
- ✅ API Key lưu trong SSM Parameter Store (miễn phí)
- ✅ Có thể thêm IP whitelist qua WAF
- ✅ Rate limiting qua API Gateway
- ✅ Dễ dàng rotate API key

## 📚 Chi tiết

Xem [DEPLOY_CLOUDSHELL.md](./DEPLOY_CLOUDSHELL.md) để biết thêm chi tiết.
