"""Database configuration."""

from pydantic import Field
from pydantic_settings import BaseSettings


class DatabaseSettings(BaseSettings):
    """Database configuration settings."""

    database_url: str = Field(default="postgresql+async://postgres:postgres@localhost:5432/blogify")
    database_pool_size: int = Field(default=10, description="Connection pool size")
    database_max_overflow: int = Field(default=20, description="Max overflow connections")
    database_echo: bool = Field(default=False, description="Echo SQL queries")

    class Config:
        env_prefix = "DATABASE_"


class DatabaseSettingsWrapper:
    """Wrapper to provide db_settings compatible interface using env_config."""

    def __init__(self):
        from src.config.env_config import config

        self._config = config

    @property
    def database_url(self) -> str:
        return self._config.database_url

    @property
    def redis_url(self) -> str:
        return self._config.redis_url

    @property
    def database_pool_size(self) -> int:
        return self._config.database_pool_size

    @property
    def database_max_overflow(self) -> int:
        return self._config.database_max_overflow


db_settings = DatabaseSettingsWrapper()
