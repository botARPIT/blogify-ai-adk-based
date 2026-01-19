"""Create initial database tables using Neon database."""

import asyncio
import os
import sys
from pathlib import Path

# Load .env.dev explicitly
from dotenv import load_dotenv
load_dotenv(dotenv_path=".env.dev")

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.models.repository import db_repository
from src.config.logging_config import get_logger, setup_logging

setup_logging("INFO")
logger = get_logger(__name__)


async def init_database():
    """Initialize database tables."""
    db_url = os.getenv("DATABASE_URL")
    logger.info(f"Initializing database: {db_url[:50]}...")
    
    try:
        await db_repository.create_tables()
        logger.info("✅ Database tables created successfully!")
    except Exception as e:
        logger.error(f"❌ Database initialization failed: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(init_database())
