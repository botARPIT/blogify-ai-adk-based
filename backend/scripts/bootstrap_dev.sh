#!/usr/bin/env bash
# scripts/bootstrap_dev.sh
# Deterministic local dev bootstrap for blogify-ai-adk-prod.
# Usage: bash scripts/bootstrap_dev.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo "==> [1/5] Checking Python version"
python3 --version | grep -E "3\.(11|12|13)" || {
  echo "ERROR: Python 3.11+ required. Found: $(python3 --version)"
  exit 1
}

echo "==> [2/5] Creating / activating virtualenv"
if [ ! -d "venv" ]; then
  python3 -m venv venv
fi
# shellcheck disable=SC1091
source venv/bin/activate

echo "==> [3/5] Installing dependencies (editable + dev)"
pip install --upgrade pip -q
pip install -e ".[dev]" -q

echo "==> [4/5] Copying env file if missing"
if [ ! -f ".env" ]; then
  cp .env.dev .env
  echo "    Copied .env.dev → .env"
else
  echo "    .env already exists, skipping copy"
fi

echo "==> [5/7] Checking local Postgres (localhost:5432)"
python3 - <<'PY'
import socket, sys
s = socket.socket()
try:
    s.settimeout(2)
    s.connect(("127.0.0.1", 5432))
except OSError:
    print("ERROR: Postgres is not reachable on localhost:5432. Start the blogify-ai-postgres container.")
    sys.exit(1)
finally:
    s.close()
PY

echo "==> [6/7] Checking local Redis (localhost:6479)"
python3 - <<'PY'
import socket, sys
s = socket.socket()
try:
    s.settimeout(2)
    s.connect(("127.0.0.1", 6479))
except OSError:
    print("ERROR: Redis is not reachable on localhost:6479. Start the blogify-ai-redis container.")
    sys.exit(1)
finally:
    s.close()
PY

echo "==> [7/7] Running Alembic migrations and smoke tests"
alembic upgrade head
pytest tests/smoke/ -v --tb=short

echo ""
echo "✅  Bootstrap complete. Activate the venv with:"
echo "    source venv/bin/activate"
echo ""
echo "Then run the API:"
echo "    bash scripts/run_api.sh"
echo ""
echo "And the worker (separate terminal):"
echo "    bash scripts/run_worker.sh"
