"""Startup configuration and dependency checks."""

import asyncio
import os
import sys
from typing import List, Tuple

import redis.asyncio as redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from src.config.database_config import db_settings
from src.config.env_config import config
from src.config.logging_config import get_logger

logger = get_logger(__name__)


class StartupCheck:
    """Validate all dependencies before starting the service."""

    def __init__(self) -> None:
        self.checks_passed = 0
        self.checks_failed = 0
        self.errors: List[str] = []

    async def check_environment_variables(self) -> bool:
        """Verify all required environment variables are set."""
        logger.info("Checking environment variables...")

        required_vars = {
            "GOOGLE_API_KEY": "Google Gemini API key",
            "TAVILY_API_KEY": "Tavily search API key",
            "DATABASE_URL": "PostgreSQL connection string",
        }

        all_present = True
        for var_name, description in required_vars.items():
            value = os.getenv(var_name)
            if not value or value.startswith("your_") or value == "":
                self.errors.append(f"❌ Missing {var_name} ({description})")
                all_present = False
            else:
                # Mask sensitive values
                masked = value[:10] + "..." if len(value) > 10 else "***"
                logger.info(f"✅ {var_name}: {masked}")

        if all_present:
            self.checks_passed += 1
            logger.info("✅ All environment variables are set")
        else:
            self.checks_failed += 1

        return all_present

    async def check_database(self) -> bool:
        """Test PostgreSQL database connectivity."""
        logger.info("Checking database connection...")

        try:
            # Create test engine
            engine = create_async_engine(
                db_settings.database_url,
                pool_pre_ping=True,
                pool_size=1,
                max_overflow=0,
            )

            # Test connection
            async with engine.begin() as conn:
                result = await conn.execute(text("SELECT 1 as test"))
                result.fetchone()

            await engine.dispose()

            self.checks_passed += 1
            logger.info("✅ Database connection successful")
            return True

        except Exception as e:
            self.checks_failed += 1
            error_msg = f"❌ Database connection failed: {str(e)}"
            self.errors.append(error_msg)
            logger.error(error_msg)
            return False

    async def check_redis(self) -> bool:
        """Test Redis connectivity."""
        logger.info("Checking Redis connection...")

        try:
            redis_client = await redis.from_url(
                db_settings.redis_url,
                decode_responses=True,
                socket_connect_timeout=5,
            )

            # Test connection
            await redis_client.ping()
            await redis_client.close()

            self.checks_passed += 1
            logger.info("✅ Redis connection successful")
            return True

        except Exception as e:
            self.checks_failed += 1
            error_msg = f"❌ Redis connection failed: {str(e)}"
            self.errors.append(error_msg)
            logger.error(error_msg)
            return False

    def check_configuration(self) -> bool:
        """Validate configuration values."""
        logger.info("Checking configuration...")

        issues = []

        # Check budget values are positive
        if config.max_concurrent_requests <= 0:
            issues.append("max_concurrent_requests must be > 0")

        if hasattr(config, "cors_origins") and config.environment == "prod":
            if not config.cors_origins or "*" in config.cors_origins:
                issues.append("CORS origins must be explicitly set in production")

        # Check port is valid
        if not (1024 <= config.api_port <= 65535):
            issues.append(f"API port {config.api_port} is out of valid range")

        if issues:
            self.checks_failed += 1
            for issue in issues:
                error_msg = f"❌ Configuration issue: {issue}"
                self.errors.append(error_msg)
                logger.error(error_msg)
            return False

        self.checks_passed += 1
        logger.info("✅ Configuration is valid")
        return True

    async def run_all_checks(self) -> Tuple[bool, List[str]]:
        """
        Run all startup checks.

        Returns:
            (all_passed, errors)
        """
        logger.info(f"🚀 Starting dependency checks for {config.environment} environment...")

        # Run checks in sequence
        env_check = await self.check_environment_variables()
        config_check = self.check_configuration()
        db_check = await self.check_database()
        redis_check = await self.check_redis()

        all_passed = env_check and config_check and db_check and redis_check

        # Summary
        logger.info("=" * 60)
        if all_passed:
            logger.info(f"✅ All checks passed ({self.checks_passed}/{self.checks_passed + self.checks_failed})")
            logger.info("🚀 Service is ready to start!")
        else:
            logger.error(f"❌ Some checks failed ({self.checks_failed}/{self.checks_passed + self.checks_failed})")
            logger.error("🛑 Service cannot start. Fix the issues above.")
            for error in self.errors:
                logger.error(f"   {error}")

        logger.info("=" * 60)

        return all_passed, self.errors


async def run_startup_checks() -> bool:
    """Run all startup checks and return success status."""
    checker = StartupCheck()
    passed, errors = await checker.run_all_checks()

    if not passed:
        sys.exit(1)  # Exit with error code if checks fail

    return passed
