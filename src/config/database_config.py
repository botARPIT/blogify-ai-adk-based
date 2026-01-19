"""Database configuration for PostgreSQL."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    """Database settings loaded from environment."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str
    database_pool_size: int = 10
    database_max_overflow: int = 20
    redis_url: str = "redis://localhost:6379/0"


# Global instance
db_settings = DatabaseSettings()
