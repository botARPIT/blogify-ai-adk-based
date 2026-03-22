#!/bin/bash
# Deploy Blogify AI to Google Cloud Run / Vertex AI
# Usage: ./scripts/deploy.sh [PROJECT_ID] [REGION]

set -e

PROJECT_ID="${1:-your-project-id}"
REGION="${2:-us-central1}"
SERVICE_NAME="blogify-api"
IMAGE_NAME="gcr.io/${PROJECT_ID}/${SERVICE_NAME}"

echo "🚀 Deploying Blogify AI to Google Cloud"
echo "Project: ${PROJECT_ID}"
echo "Region: ${REGION}"
echo "Service: ${SERVICE_NAME}"
echo ""

# Check if gcloud is installed
if ! command -v gcloud &> /dev/null; then
    echo "❌ gcloud CLI not found. Please install Google Cloud SDK."
    exit 1
fi

# Authenticate (if needed)
echo "📋 Setting project..."
gcloud config set project ${PROJECT_ID}

# Build the Docker image
echo "🔨 Building Docker image..."
docker build -t ${IMAGE_NAME}:latest .

# Push to Google Container Registry
echo "📤 Pushing to GCR..."
docker push ${IMAGE_NAME}:latest

# Deploy to Cloud Run
echo "☁️ Deploying to Cloud Run..."
gcloud run deploy ${SERVICE_NAME} \
    --image ${IMAGE_NAME}:latest \
    --platform managed \
    --region ${REGION} \
    --allow-unauthenticated \
    --memory 1Gi \
    --cpu 1 \
    --min-instances 1 \
    --max-instances 10 \
    --timeout 300 \
    --set-env-vars "ENVIRONMENT=production" \
    --set-secrets "GOOGLE_API_KEY=google-api-key:latest,TAVILY_API_KEY=tavily-api-key:latest,DATABASE_URL=database-url:latest"

echo ""
echo "✅ Deployment complete!"
echo ""

# Get the URL
URL=$(gcloud run services describe ${SERVICE_NAME} --region ${REGION} --format 'value(status.url)')
echo "🌐 Service URL: ${URL}"
echo ""

# Health check
echo "🔍 Running health check..."
curl -s "${URL}/api/health" | jq .
