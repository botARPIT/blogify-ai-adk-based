"""Create initial database tables."""

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.models.repository import db_repository
from src.config.logging_config import get_logger, setup_logging

setup_logging("INFO")
logger = get_logger(__name__)


async def init_database():
    """Initialize database tables."""
    logger.info("Initializing database...")
    
    try:
        await db_repository.create_tables()
        logger.info("Database tables created successfully!")
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(init_database())
