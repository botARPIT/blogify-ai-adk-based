#!/bin/bash
# Deploy Blogify AI to EC2
# Usage: ./deploy.sh [mode] [environment]
#   mode: local or vpc (default: local)
#   environment: staging or production (default: staging)

set -e

MODE="${1:-local}"
ENVIRONMENT="${2:-staging}"

PROJECT_ID="${PROJECT_ID:-your-project-id}"
REGION="${REGION:-us-central1}"
SERVICE_NAME="blogify-api"
IMAGE_NAME="ghcr.io/${PROJECT_ID}/${SERVICE_NAME}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE=""

if [ "$MODE" = "local" ]; then
    COMPOSE_FILE="docker-compose.local.yml"
elif [ "$MODE" = "vpc" ]; then
    COMPOSE_FILE="docker-compose.vpc.yml"
else
    echo "ERROR: Invalid mode. Use 'local' or 'vpc'"
    exit 1
fi

echo "========================================="
echo "  Blogify AI Deployment"
echo "========================================="
echo "Mode: ${MODE}"
echo "Environment: ${ENVIRONMENT}"
echo "Compose file: ${COMPOSE_FILE}"
echo ""

if ! command -v docker &> /dev/null; then
    echo "ERROR: Docker not found. Please install Docker."
    exit 1
fi

if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
    echo "ERROR: docker-compose not found. Please install Docker Compose."
    exit 1
fi

DOCKER_COMPOSE_CMD="docker compose"
if ! docker compose version &> /dev/null; then
    DOCKER_COMPOSE_CMD="docker-compose"
fi

echo "Loading environment from .env.${ENVIRONMENT}..."
if [ -f "${SCRIPT_DIR}/../.env.${ENVIRONMENT}" ]; then
    set -a
    source "${SCRIPT_DIR}/../.env.${ENVIRONMENT}"
    set +a
else
    echo "WARNING: .env.${ENVIRONMENT} not found, using .env if exists"
    if [ -f "${SCRIPT_DIR}/../.env" ]; then
        set -a
        source "${SCRIPT_DIR}/../.env"
        set +a
    fi
fi

echo "Pulling latest images..."
${DOCKER_COMPOSE_CMD} -f "${COMPOSE_FILE}" pull

echo "Stopping existing containers..."
${DOCKER_COMPOSE_CMD} -f "${COMPOSE_FILE}" down

echo "Starting services..."
${DOCKER_COMPOSE_CMD} -f "${COMPOSE_FILE}" up -d

echo ""
echo "========================================="
echo "  Deployment Complete!"
echo "========================================="
echo ""

echo "Checking service health..."
sleep 5

API_HEALTH=$(${DOCKER_COMPOSE_CMD} -f "${COMPOSE_FILE}" ps api 2>/dev/null | grep -c "Up" || echo "0")
WORKER_HEALTH=$(${DOCKER_COMPOSE_CMD} -f "${COMPOSE_FILE}" ps worker 2>/dev/null | grep -c "Up" || echo "0")

if [ "$API_HEALTH" -gt 0 ]; then
    echo "  ✓ API service is running"
else
    echo "  ✗ API service is not running"
fi

if [ "$WORKER_HEALTH" -gt 0 ]; then
    echo "  ✓ Worker service is running"
else
    echo "  ✗ Worker service is not running"
fi

echo ""
echo "Run '${DOCKER_COMPOSE_CMD} -f ${COMPOSE_FILE} logs -f' to view logs"