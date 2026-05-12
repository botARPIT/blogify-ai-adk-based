"""Environment loader for worker and other processes.

DEPRECATED: This module is no longer needed. Environment variables are now
loaded automatically when src.config.env_config is imported.

This file is kept for backward compatibility but should not be used in new code.
"""

import os
import warnings

from dotenv import load_dotenv


def ensure_env_loaded() -> None:
    """Load environment variables from .env files.
    
    DEPRECATED: No longer needed. Import src.config.env_config directly instead.
    """
    warnings.warn(
        "ensure_env_loaded() is deprecated. Environment variables are now "
        "loaded automatically when importing src.config.env_config",
        DeprecationWarning,
        stacklevel=2,
    )
    env = os.getenv("ENVIRONMENT", "dev")
    load_dotenv(f".env.{env}")
    load_dotenv(f".env.{env}", override=True)
