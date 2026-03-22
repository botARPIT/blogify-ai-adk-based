#!/usr/bin/env bash
# scripts/run_api.sh
# Start the FastAPI dev server.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# Load env from multiple locations (priority: backend/.env -> root/.env -> root/.env.dev)
for env_file in ".env" "../.env" "../.env.dev"; do
  if [ -f "$env_file" ]; then
    echo "==> Loading environment from $env_file"
    # shellcheck disable=SC2046
    export $(grep -v '^#' "$env_file" | xargs)
  fi
done

: "${GOOGLE_API_KEY:?'GOOGLE_API_KEY is required. Set it in .env'}"
: "${TAVILY_API_KEY:?'TAVILY_API_KEY is required. Set it in .env'}"
: "${DATABASE_URL:?'DATABASE_URL is required. Set it in .env'}"

export ENVIRONMENT="${ENVIRONMENT:-dev}"
export PYTHONPATH="$REPO_ROOT"
# Ensure log level is lowercase for uvicorn
LOG_LEVEL_LOWER=$(echo "${LOG_LEVEL:-info}" | tr '[:upper:]' '[:lower:]')

echo "==> Starting Blogify AI API (env=$ENVIRONMENT)"
uvicorn src.api.main:app \
  --host "${API_HOST:-0.0.0.0}" \
  --port "${API_PORT:-8000}" \
  --reload \
  --log-level "$LOG_LEVEL_LOWER"
