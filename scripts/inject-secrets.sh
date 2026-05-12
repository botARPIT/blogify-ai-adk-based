#!/bin/bash
# inject-secrets.sh — Fetch BlogifyAI secrets from AWS Secrets Manager.
# Runs on EC2 using the attached IAM role (blogifyai-ec2-role).
#
# Usage:
#   ./scripts/inject-secrets.sh

set -euo pipefail

SECRET_NAME="${AWS_SECRET_NAME:-blogify/production}"
REGION="${AWS_REGION:-ap-south-1}"
OUTPUT="${DEPLOY_DIR:-/home/ubuntu/blogifyai}/.env"

echo "Fetching secret '${SECRET_NAME}' from region '${REGION}'..."

aws secretsmanager get-secret-value \
  --secret-id "${SECRET_NAME}" \
  --region "${REGION}" \
  --query SecretString \
  --output text \
| python3 -c "
import sys, json
for k, v in json.load(sys.stdin).items():
    print(f'{k}={v}')
" > "${OUTPUT}"

chmod 600 "${OUTPUT}"
echo "Secrets written to ${OUTPUT}"
