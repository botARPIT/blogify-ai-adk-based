"""Environment loader for worker and other processes.

This module loads environment variables from .env files at startup.
Import this before any other modules that need environment variables.

Usage:
    from src.config.env_loader import ensure_env_loaded
    ensure_env_loaded()
"""

import os
from dotenv import load_dotenv


def ensure_env_loaded() -> None:
    """Load environment variables from .env files."""
    env = os.getenv("ENVIRONMENT", "dev")
    load_dotenv(f".env.{env}")
    load_dotenv(f".env.{env}", override=True)


ensure_env_loaded()