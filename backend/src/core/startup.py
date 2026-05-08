"""Runtime manager for application lifecycle and health checks."""

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Optional

from src.config.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class HealthCheckResult:
    """Result of a health check."""

    name: str
    status: str
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class HealthReport:
    """Aggregated health report."""

    status: str
    is_healthy: bool
    checks: list[HealthCheckResult]
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "is_healthy": self.is_healthy,
            "checks": [
                {
                    "name": c.name,
                    "status": c.status,
                    "message": c.message,
                    "details": c.details,
                    "timestamp": c.timestamp.isoformat(),
                }
                for c in self.checks
            ],
            "timestamp": self.timestamp.isoformat(),
        }


class RuntimeManager:
    """Manages application runtime and health checks."""

    _instance: Optional["RuntimeManager"] = None
    _start_time: datetime = field(default_factory=datetime.utcnow)

    def __new__(cls) -> "RuntimeManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @property
    def started_at(self) -> datetime:
        return self._start_time

    def uptime(self) -> timedelta:
        return datetime.utcnow() - self._start_time

    async def collect_health_report(
        self, service: str = "api", include_workers: bool = False
    ) -> HealthReport:
        """Collect health report from all dependencies."""
        checks = []

        db_check = await self._check_database()
        checks.append(db_check)

        redis_check = await self._check_redis()
        checks.append(redis_check)

        if include_workers:
            workers_check = await self._check_workers()
            checks.append(workers_check)

        is_healthy = all(c.status == "healthy" for c in checks)
        status = "healthy" if is_healthy else "unhealthy"

        return HealthReport(
            status=status,
            is_healthy=is_healthy,
            checks=checks,
        )

    async def _check_database(self) -> HealthCheckResult:
        """Check database connectivity."""
        try:
            from src.core.database import AsyncSessionFactory

            async with AsyncSessionFactory() as session:
                await session.execute("SELECT 1")
            return HealthCheckResult(
                name="database",
                status="healthy",
                message="Database connection OK",
            )
        except Exception as e:
            logger.error("health_check_db_failed", error=str(e))
            return HealthCheckResult(
                name="database",
                status="unhealthy",
                message=f"Database check failed: {str(e)}",
            )

    async def _check_redis(self) -> HealthCheckResult:
        """Check Redis connectivity."""
        try:
            from src.core.redis_pool import get_redis_client

            redis = await get_redis_client()
            await redis.ping()
            return HealthCheckResult(
                name="redis",
                status="healthy",
                message="Redis connection OK",
            )
        except Exception as e:
            logger.error("health_check_redis_failed", error=str(e))
            return HealthCheckResult(
                name="redis",
                status="unhealthy",
                message=f"Redis check failed: {str(e)}",
            )

    async def _check_workers(self) -> HealthCheckResult:
        """Check worker health via Redis."""
        try:
            import redis.asyncio as redis

            from src.config.env_config import config

            r = redis.from_url(config.redis_url)
            workers = []
            for key in await r.keys("blogify:worker:*"):
                value = await r.get(key)
                if value:
                    workers.append(key.decode())

            await r.aclose()

            if workers:
                return HealthCheckResult(
                    name="workers",
                    status="healthy",
                    message=f"{len(workers)} workers active",
                    details={"worker_count": len(workers), "workers": workers},
                )
            else:
                return HealthCheckResult(
                    name="workers",
                    status="warning",
                    message="No active workers found",
                    details={"worker_count": 0},
                )
        except Exception as e:
            logger.error("health_check_workers_failed", error=str(e))
            return HealthCheckResult(
                name="workers",
                status="unhealthy",
                message=f"Worker check failed: {str(e)}",
            )


runtime_manager = RuntimeManager()