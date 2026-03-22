#!/usr/bin/env bash
# scripts/seed_dev_data.sh
# Seed the local dev database with initial data for testing.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

if [ -f ".env" ]; then
  # shellcheck disable=SC2046
  export $(grep -v '^#' .env | xargs)
fi

: "${DATABASE_URL:?'DATABASE_URL is required'}"

export PYTHONPATH="$REPO_ROOT"

echo "==> Running Alembic migrations"
alembic upgrade head

echo "==> Seeding default service client, tenant, and budget policy"
python3 - <<'PYEOF'
import asyncio
import os
from src.config.database_config import db_settings

async def seed():
    print("  Seed: inserting default dev data...")
    # Placeholder: actual seed logic executes once canonical models exist (Phase 1)
    print("  Seed: Phase 1 tables not yet created. Run again after Phase 1 migration.")

asyncio.run(seed())
PYEOF

echo "✅ Seed complete."
