#!/bin/bash

# Lưu các biến môi trường hiện tại (nếu có) để khôi phục sau này
if [ ! -z "$AWS_PROFILE" ]; then
  export OLD_AWS_PROFILE=$AWS_PROFILE
fi
if [ ! -z "$AWS_ACCESS_KEY_ID" ]; then
  export OLD_AWS_ACCESS_KEY_ID=$AWS_ACCESS_KEY_ID
fi
if [ ! -z "$AWS_SECRET_ACCESS_KEY" ]; then
  export OLD_AWS_SECRET_ACCESS_KEY=$AWS_SECRET_ACCESS_KEY
fi
if [ ! -z "$AWS_DEFAULT_REGION" ]; then
  export OLD_AWS_DEFAULT_REGION=$AWS_DEFAULT_REGION
fi

# Thiết lập biến môi trường cho dự án này
export AWS_PROFILE=seedcom-chatbot

echo "=============================================="
echo "AWS Credentials được thiết lập cho dự án Seedcom Chatbot"
echo "Profile: $AWS_PROFILE"
echo "=============================================="
echo "Để kết thúc và khôi phục biến môi trường cũ, chạy: source end-project.sh"
echo "Hoặc mở một terminal mới"

# Kích hoạt môi trường ảo và thiết lập biến môi trường khác nếu cần
source venv/bin/activate
source setenv.sh