#!/usr/bin/env bash
# scripts/run_api.sh
# Start the FastAPI dev server.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# Load env if present
if [ -f ".env" ]; then
  # shellcheck disable=SC2046
  export $(grep -v '^#' .env | xargs)
fi

: "${GOOGLE_API_KEY:?'GOOGLE_API_KEY is required. Set it in .env'}"
: "${TAVILY_API_KEY:?'TAVILY_API_KEY is required. Set it in .env'}"
: "${DATABASE_URL:?'DATABASE_URL is required. Set it in .env'}"

export ENVIRONMENT="${ENVIRONMENT:-dev}"
export PYTHONPATH="$REPO_ROOT"

echo "==> Starting Blogify AI API (env=$ENVIRONMENT)"
uvicorn src.api.main:app \
  --host "${API_HOST:-0.0.0.0}" \
  --port "${API_PORT:-8000}" \
  --reload \
  --log-level "${LOG_LEVEL:-info}"
