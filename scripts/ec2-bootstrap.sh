#!/bin/bash
# ec2-bootstrap.sh — Run ONCE on a fresh Ubuntu 24.04 LTS EC2 instance.
# Installs: Docker Engine, Docker Compose plugin, AWS CLI v2
# Creates: /home/ubuntu/blogifyai directory layout
#
# Usage:
#   chmod +x ec2-bootstrap.sh && sudo ./ec2-bootstrap.sh
#
# NOTE: After this script, you still need to:
#   1. Copy docker-compose.prod.yml, monitoring/, nginx/ dirs to /home/ubuntu/blogifyai/
#   2. Attach the `blogifyai-ec2-role` IAM role to the instance
#   3. Point api.blogifyai.arpitdev.site DNS A record to this instance's public IP
#   4. Add your SSH public key to /home/ubuntu/.ssh/authorized_keys (for GitHub Actions)

set -euo pipefail

DEPLOY_USER="ubuntu"
DEPLOY_DIR="/home/${DEPLOY_USER}/blogifyai"

echo "==> [1/5] Updating system packages..."
apt-get update -y
apt-get upgrade -y
apt-get install -y ca-certificates curl gnupg unzip lsb-release

echo "==> [2/5] Installing Docker Engine + Compose plugin..."
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu \
  $(lsb_release -cs) stable" \
  | tee /etc/apt/sources.list.d/docker.list > /dev/null

apt-get update -y
apt-get install -y \
  docker-ce docker-ce-cli containerd.io \
  docker-buildx-plugin docker-compose-plugin

# Allow ubuntu user to run docker without sudo
usermod -aG docker "${DEPLOY_USER}"
systemctl enable docker
systemctl start docker

echo "==> [3/5] Installing AWS CLI v2..."
curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o /tmp/awscliv2.zip
unzip -q /tmp/awscliv2.zip -d /tmp/awscli-install
/tmp/awscli-install/aws/install --update
rm -rf /tmp/awscliv2.zip /tmp/awscli-install

echo "==> [4/5] Creating deploy directory layout..."
mkdir -p "${DEPLOY_DIR}"/{nginx,monitoring,grafana/provisioning}
chown -R "${DEPLOY_USER}:${DEPLOY_USER}" "${DEPLOY_DIR}"

echo "==> [5/5] Verifying installations..."
docker --version
docker compose version
aws --version

echo ""
echo "✅ Bootstrap complete."
echo ""
echo "Next steps:"
echo "  1. scp docker-compose.prod.yml ubuntu@<ec2-ip>:${DEPLOY_DIR}/"
echo "  2. scp -r backend/nginx ubuntu@<ec2-ip>:${DEPLOY_DIR}/"
echo "  3. scp -r backend/monitoring ubuntu@<ec2-ip>:${DEPLOY_DIR}/"
echo "  4. Attach IAM role 'blogifyai-ec2-role' in EC2 console → Actions → Security"
echo "  5. Point api.blogifyai.arpitdev.site → this instance's public IP"
echo "  6. Add the deploy SSH public key to ~/.ssh/authorized_keys"
