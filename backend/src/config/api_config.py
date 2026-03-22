"""API configuration for FastAPI server."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class APISettings(BaseSettings):
    """API server settings loaded from environment."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Server settings
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_workers: int = 4
    log_level: str = "INFO"

    # Rate limiting
    rate_limit_blogs_per_day: int = 10
    rate_limit_requests_per_minute: int = 20

    # Concurrency
    max_concurrent_requests: int = 10

    # Circuit breaker
    circuit_breaker_failure_threshold: int = 5
    circuit_breaker_recovery_timeout: int = 60  # seconds

    # Monitoring
    enable_metrics: bool = True
    metrics_port: int = 9090


# Global instance
settings = APISettings()
