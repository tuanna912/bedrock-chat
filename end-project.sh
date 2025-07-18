#!/bin/bash

# Khôi phục biến môi trường cũ
if [ ! -z "$OLD_AWS_PROFILE" ]; then
  export AWS_PROFILE=$OLD_AWS_PROFILE
  unset OLD_AWS_PROFILE
else
  unset AWS_PROFILE
fi

if [ ! -z "$OLD_AWS_ACCESS_KEY_ID" ]; then
  export AWS_ACCESS_KEY_ID=$OLD_AWS_ACCESS_KEY_ID
  unset OLD_AWS_ACCESS_KEY_ID
else
  unset AWS_ACCESS_KEY_ID
fi

if [ ! -z "$OLD_AWS_SECRET_ACCESS_KEY" ]; then
  export AWS_SECRET_ACCESS_KEY=$OLD_AWS_SECRET_ACCESS_KEY
  unset OLD_AWS_SECRET_ACCESS_KEY
else
  unset AWS_SECRET_ACCESS_KEY
fi

if [ ! -z "$OLD_AWS_DEFAULT_REGION" ]; then
  export AWS_DEFAULT_REGION=$OLD_AWS_DEFAULT_REGION
  unset OLD_AWS_DEFAULT_REGION
else
  unset AWS_DEFAULT_REGION
fi

# Deactivate virtual env
deactivate

echo "=============================================="
echo "AWS Credentials đã được khôi phục về trạng thái ban đầu"
echo "=============================================="