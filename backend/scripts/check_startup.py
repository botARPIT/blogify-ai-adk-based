"""Standalone startup check script - run before starting the service."""

import asyncio
import sys
from pathlib import Path

# Load environment
from dotenv import load_dotenv
load_dotenv(dotenv_path=".env.dev")

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config.logging_config import setup_logging
from src.core.startup import run_startup_checks

setup_logging("INFO")


async def main():
    """Run startup checks."""
    await run_startup_checks()


if __name__ == "__main__":
    asyncio.run(main())
