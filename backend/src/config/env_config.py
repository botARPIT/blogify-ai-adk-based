"""Environment-specific configuration loader."""

import os
from enum import Enum
from typing import Any

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(str, Enum):
    """Environment types."""

    DEV = "dev"
    STAGE = "stage"
    PROD = "prod"


# Determine base directories
CONFIG_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.dirname(CONFIG_DIR)
BACKEND_ROOT = os.path.dirname(SRC_DIR)


class BaseConfig(BaseSettings):
    """Base configuration."""

    model_config = SettingsConfigDict(extra="ignore")

    # Environment
    environment: Environment = Environment.DEV

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_workers: int = 2
    log_level: str = "info"

    # CORS
    cors_origins: str = "*"
    cors_allow_credentials: bool = True

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: Any) -> list[str]:
        """Parse CORS origins if provided as a string or list."""
        if not v:
            return ["*"]
        if isinstance(v, str):
            v_strip = v.strip()
            if not v_strip:
                return ["*"]
            try:
                # Try JSON first
                import json

                return json.loads(v_strip)
            except json.JSONDecodeError:
                # Fallback to comma-separated
                return [s.strip() for s in v_strip.split(",")]
        return v

    # Database
    database_url: str
    database_pool_size: int = 10
    database_max_overflow: int = 20

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Rate limiting
    rate_limit_blogs_per_day: int = 10
    rate_limit_requests_per_minute: int = 20

    # Concurrency
    max_concurrent_requests: int = 10

    # Circuit breaker
    circuit_breaker_failure_threshold: int = 5
    circuit_breaker_recovery_timeout: int = 60

    # Monitoring
    enable_metrics: bool = True
    metrics_port: int = 9090
    enable_datadog: bool = False
    datadog_api_key: str | None = None

    # Worker health
    worker_heartbeat_interval_seconds: int = 15
    worker_heartbeat_ttl_seconds: int = 45

    # Feature flags
    enable_canonical_routes: bool = False


class DevelopmentConfig(BaseConfig):
    """Development environment configuration."""

    model_config = SettingsConfigDict(
        env_file=[
            os.path.join(BACKEND_ROOT, ".env.dev"),
            os.path.join(BACKEND_ROOT, ".env"),
            ".env.dev",
            ".env",
        ],
        env_file_encoding="utf-8",
    )

    environment: Environment = Environment.DEV
    log_level: str = "debug"
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:8000"]
    enable_datadog: bool = False


class StagingConfig(BaseConfig):
    """Staging environment configuration."""

    model_config = SettingsConfigDict(
        env_file=[
            os.path.join(BACKEND_ROOT, ".env.stage"),
            ".env.stage",
        ],
        env_file_encoding="utf-8",
    )

    environment: Environment = Environment.STAGE
    log_level: str = "info"
    api_workers: int = 4
    max_concurrent_requests: int = 20
    enable_datadog: bool = True


class ProductionConfig(BaseConfig):
    """Production environment configuration."""

    model_config = SettingsConfigDict(
        env_file=[
            os.path.join(BACKEND_ROOT, ".env.prod"),
            ".env.prod",
        ],
        env_file_encoding="utf-8",
    )

    environment: Environment = Environment.PROD
    log_level: str = "warning"
    api_workers: int = 8
    max_concurrent_requests: int = 50
    cors_origins: list[str] = []  # Must be explicitly set in prod
    cors_allow_credentials: bool = False
    enable_datadog: bool = True
    enable_canonical_routes: bool = True


def get_config() -> BaseConfig:
    """Get configuration based on environment variable."""
    env = os.getenv("ENVIRONMENT", "dev").lower()

    config_map = {
        "dev": DevelopmentConfig,
        "stage": StagingConfig,
        "prod": ProductionConfig,
    }

    config_class = config_map.get(env, DevelopmentConfig)
    return config_class()


# Global config instance
config = get_config()
