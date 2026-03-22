#!/usr/bin/env bash
# scripts/run_worker.sh
# Start the background blog generation worker.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

if [ -f ".env" ]; then
  # shellcheck disable=SC2046
  export $(grep -v '^#' .env | xargs)
fi

: "${GOOGLE_API_KEY:?'GOOGLE_API_KEY is required'}"
: "${TAVILY_API_KEY:?'TAVILY_API_KEY is required'}"
: "${DATABASE_URL:?'DATABASE_URL is required'}"

export ENVIRONMENT="${ENVIRONMENT:-dev}"
export PYTHONPATH="$REPO_ROOT"

echo "==> Starting Blogify AI Worker (env=$ENVIRONMENT)"
python3 -m src.workers.blog_worker
