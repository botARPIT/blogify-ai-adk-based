#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

if [ -d "venv" ]; then
  # shellcheck disable=SC1091
  source venv/bin/activate
fi

export ENVIRONMENT="${ENVIRONMENT:-dev}"
export PYTHONPATH="$REPO_ROOT"
ENV_FILE=".env.${ENVIRONMENT}"

if [ -f "$ENV_FILE" ]; then
  cp -f "$ENV_FILE" .env
  export DATABASE_URL="$(grep '^DATABASE_URL=' "$ENV_FILE" | cut -d= -f2-)"
fi

echo "==> Running Alembic migrations for backend (env=$ENVIRONMENT)"
exec alembic upgrade head
