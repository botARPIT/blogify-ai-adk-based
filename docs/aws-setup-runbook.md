# AWS Setup Runbook — BlogifyAI EC2 Phase 1

## 1. Create IAM Role for EC2

### 1a. Trust Policy
In the AWS Console → IAM → Roles → Create Role:
- **Trusted entity**: AWS service → EC2
- **Role name**: `blogifyai-ec2-role`

### 1b. Inline Permission Policy
Attach the following inline policy (replace `<account-id>`):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ReadBlogifyAISecret",
      "Effect": "Allow",
      "Action": [
        "secretsmanager:GetSecretValue",
        "secretsmanager:DescribeSecret"
      ],
      "Resource": "arn:aws:secretsmanager:ap-south-1:<account-id>:secret:blogifyai/production*"
    }
  ]
}
```

> [!IMPORTANT]
> The wildcard `*` at the end of the ARN is required because AWS appends a random 6-character suffix to the secret ARN when it is created.

---

## 2. Create the Secret in AWS Secrets Manager

Region: `ap-south-1`  
Secret name: `blogifyai/production`  
Secret type: **Other type of secret → Plaintext → JSON**

Paste the following JSON (fill in your real values):

```json
{
  "POSTGRES_DB": "blogifyai",
  "POSTGRES_USER": "blogifyai",
  "POSTGRES_PASSWORD": "<generate-strong-password>",
  "DATABASE_URL": "postgresql+asyncpg://blogifyai:<password>@postgres:5432/blogifyai",
  "REDIS_URL": "redis://redis:6379/0",
  "GOOGLE_API_KEY": "<your-gemini-key>",
  "TAVILY_API_KEY": "<your-tavily-key>",
  "GRAFANA_USER": "admin",
  "GRAFANA_PASSWORD": "<generate-strong-password>",
  "JWT_SECRET": "<generate-64-char-random-string>",
  "ADMIN_API_KEY": "<generate-strong-random-string>",
  "CORS_ORIGINS": "[\"https://blogifyai.arpitdev.site\"]",
  "ENVIRONMENT": "production",
  "LETSENCRYPT_EMAIL": "arpit@arpitdev.site"
}
```

> [!NOTE]
> `SESSION_SECRET` is not required — the backend uses `JWT_SECRET` for authentication.  
> `ADMIN_API_KEY` gates the `/internal/ai/*` routes.

---

## 3. Launch EC2 Instance

| Setting | Value |
|---|---|
| AMI | Ubuntu Server 24.04 LTS (amd64) |
| Instance type | `t3.medium` |
| Region | `ap-south-1` |
| IAM instance profile | `blogifyai-ec2-role` |
| Security group — Inbound | Port 22 (SSH, your IP only), 80 (HTTP, 0.0.0.0/0), 443 (HTTPS, 0.0.0.0/0) |
| Storage | 30 GB gp3 |
| Key pair | Use or create one; save the `.pem` |

---

## 4. Bootstrap the Instance

```bash
# Copy bootstrap script
scp -i <your-key.pem> scripts/ec2-bootstrap.sh ubuntu@<ec2-ip>:~

# SSH and run
ssh -i <your-key.pem> ubuntu@<ec2-ip>
sudo bash ~/ec2-bootstrap.sh
```

---

## 5. Copy App Files to EC2

```bash
# From repo root
scp -i <your-key.pem> backend/docker-compose.prod.yml \
    ubuntu@<ec2-ip>:/home/ubuntu/blogifyai/

scp -i <your-key.pem> -r backend/nginx \
    ubuntu@<ec2-ip>:/home/ubuntu/blogifyai/

scp -i <your-key.pem> -r backend/monitoring \
    ubuntu@<ec2-ip>:/home/ubuntu/blogifyai/
```

---

## 6. Add GitHub Secrets

In GitHub → repo → Settings → Secrets and variables → Actions:

| Secret | Value |
|---|---|
| `DOCKERHUB_USERNAME` | `iarpitchauhan` |
| `DOCKERHUB_TOKEN` | Docker Hub access token (read/write) |
| `EC2_HOST` | EC2 public IP or DNS |
| `EC2_SSH_KEY` | Contents of the `.pem` private key file |
| `AWS_REGION` | `ap-south-1` |
| `AWS_SECRET_NAME` | `blogifyai/production` |

---

## 7. DNS Configuration

Point an **A record** in your DNS provider:

```
api.blogifyai.arpitdev.site  →  <EC2 public IP>
```

Wait for DNS propagation (usually < 5 minutes with TTL=300), then trigger a deploy from `main` — acme-companion will auto-issue the TLS certificate.

---

## 8. Verify

```bash
# Health endpoint
curl https://api.blogifyai.arpitdev.site/api/health

# Grafana (SSH tunnel)
ssh -L 3000:localhost:3000 ubuntu@<ec2-ip>
# open http://localhost:3000

# Prometheus (SSH tunnel)
ssh -L 9090:localhost:9090 ubuntu@<ec2-ip>
# open http://localhost:9090
```
