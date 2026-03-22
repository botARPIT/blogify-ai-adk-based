"""Initialize the local database schema using Alembic migrations only."""

import os
import subprocess
import sys
from pathlib import Path

# Load .env.dev explicitly
from dotenv import load_dotenv
load_dotenv(dotenv_path=".env.dev")

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config.logging_config import get_logger, setup_logging

setup_logging("INFO")
logger = get_logger(__name__)


def init_database():
    """Initialize database schema via `alembic upgrade head`."""
    db_url = os.getenv("DATABASE_URL")
    logger.info(f"Initializing database schema via Alembic: {db_url[:50]}...")

    try:
        subprocess.run(["alembic", "upgrade", "head"], check=True)
        logger.info("✅ Database schema migrated successfully!")
    except Exception as e:
        logger.error(f"❌ Database initialization failed: {e}")
        raise


if __name__ == "__main__":
    init_database()
