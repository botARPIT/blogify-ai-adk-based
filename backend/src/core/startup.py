"""Centralized runtime management for startup, health, and shutdown."""

from __future__ import annotations

import asyncio
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from src.config.database_config import db_settings
from src.config.env_config import config
from src.config.logging_config import get_logger
from src.core.redis_pool import close_pool as close_redis_pool, get_redis_client
from src.core.task_queue import task_queue
from src.guards.rate_limit_guard import rate_limit_guard
from src.models.repository import db_repository
from src.services.local_auth_service import LocalAuthService

logger = get_logger(__name__)


@dataclass
class ServiceCheck:
    """Health check result for a single dependency or subsystem."""

    name: str
    status: str
    critical: bool
    message: str | None = None
    latency_ms: float | None = None
    details: dict[str, Any] = field(default_factory=dict)
    checked_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> dict[str, Any]:
        """Serialize the check result for API responses."""
        data = asdict(self)
        return {key: value for key, value in data.items() if value not in (None, {}, [])}


@dataclass
class StartupReport:
    """Aggregated startup or health report."""

    service_name: str
    checks: dict[str, ServiceCheck]
    generated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    @property
    def is_healthy(self) -> bool:
        """Return True when all critical checks are healthy."""
        return all(
            check.status == "healthy"
            for check in self.checks.values()
            if check.critical
        )

    @property
    def status(self) -> str:
        """Overall status string."""
        if self.is_healthy and all(check.status == "healthy" for check in self.checks.values()):
            return "healthy"
        if self.is_healthy:
            return "degraded"
        return "unhealthy"

    def to_dict(self) -> dict[str, Any]:
        """Serialize the report for API responses."""
        return {
            "service": self.service_name,
            "status": self.status,
            "generated_at": self.generated_at,
            "checks": {name: check.to_dict() for name, check in self.checks.items()},
        }


class StartupCheckError(RuntimeError):
    """Raised when critical startup checks fail."""

    def __init__(self, report: StartupReport):
        self.report = report
        failed = [
            f"{name}: {check.message or check.status}"
            for name, check in report.checks.items()
            if check.critical and check.status != "healthy"
        ]
        message = "Startup checks failed"
        if failed:
            message = f"{message}: {', '.join(failed)}"
        super().__init__(message)


class RuntimeManager:
    """Own startup validation, health reporting, worker heartbeats, and shutdown."""

    WORKER_REGISTRY_KEY = "blogify:workers:registry"
    WORKER_KEY_PREFIX = "blogify:workers:"

    def __init__(self) -> None:
        self.started_at = datetime.utcnow()
        self._worker_tasks: dict[str, asyncio.Task] = {}

    async def _create_redis_client(self):
        """Return a Redis client backed by the shared pool."""
        return get_redis_client()

    def _required_environment_variables(self) -> dict[str, str]:
        """Return required environment variables for service startup."""
        return {
            "GOOGLE_API_KEY": "Google Gemini API key",
            "TAVILY_API_KEY": "Tavily search API key",
            "DATABASE_URL": "PostgreSQL connection string",
            "REDIS_URL": "Redis connection string",
        }

    async def check_environment_variables(self) -> ServiceCheck:
        """Verify required environment variables are present."""
        missing: list[str] = []
        for name, description in self._required_environment_variables().items():
            value = os.getenv(name)
            if not value or value.startswith("your_"):
                missing.append(f"{name} ({description})")

        if missing:
            return ServiceCheck(
                name="environment",
                status="unhealthy",
                critical=True,
                message="Missing required environment variables",
                details={"missing": missing},
            )

        return ServiceCheck(
            name="environment",
            status="healthy",
            critical=True,
            message="Required environment variables are set",
        )

    def check_configuration(self) -> ServiceCheck:
        """Validate central configuration before startup."""
        issues: list[str] = []
        auth_service = LocalAuthService()

        if config.max_concurrent_requests <= 0:
            issues.append("max_concurrent_requests must be > 0")

        if not (1024 <= config.api_port <= 65535):
            issues.append(f"api_port {config.api_port} is out of range")

        if hasattr(config, "cors_origins") and config.environment == "prod":
            if not config.cors_origins or "*" in config.cors_origins:
                issues.append("cors_origins must be explicitly set in production")

        if config.environment in {"stage", "prod"} and getattr(config, "log_format", "json") != "json":
            issues.append("log_format must be json in stage and production")

        if config.environment == "prod" and auth_service.is_production_secret_invalid():
            issues.append("JWT_SECRET_KEY must be explicitly set in production")

        if (
            config.environment in {"stage", "prod"}
            and getattr(config, "enable_admin_routes", False)
            and not getattr(config, "admin_api_key", None)
        ):
            issues.append("ADMIN_API_KEY must be explicitly set when admin routes are enabled")

        if config.worker_heartbeat_ttl_seconds <= config.worker_heartbeat_interval_seconds:
            issues.append("worker_heartbeat_ttl_seconds must be greater than worker_heartbeat_interval_seconds")

        if issues:
            return ServiceCheck(
                name="configuration",
                status="unhealthy",
                critical=True,
                message="Invalid configuration values",
                details={"issues": issues},
            )

        return ServiceCheck(
            name="configuration",
            status="healthy",
            critical=True,
            message="Configuration validated",
        )

    async def check_database(self) -> ServiceCheck:
        """Test PostgreSQL connectivity."""
        engine = None
        started = datetime.utcnow()

        try:
            engine = create_async_engine(
                db_settings.database_url,
                pool_pre_ping=True,
                pool_size=1,
                max_overflow=0,
                connect_args={"timeout": 5},
            )
            async with engine.begin() as conn:
                await conn.execute(text("SELECT 1"))

            latency_ms = (datetime.utcnow() - started).total_seconds() * 1000
            return ServiceCheck(
                name="database",
                status="healthy",
                critical=True,
                message="Database connection successful",
                latency_ms=round(latency_ms, 2),
            )
        except Exception as exc:
            return ServiceCheck(
                name="database",
                status="unhealthy",
                critical=True,
                message=str(exc),
            )
        finally:
            if engine is not None:
                await engine.dispose()

    async def check_redis(self) -> ServiceCheck:
        """Test Redis connectivity."""
        client = None
        started = datetime.utcnow()

        try:
            client = await self._create_redis_client()
            await client.ping()
            latency_ms = (datetime.utcnow() - started).total_seconds() * 1000
            return ServiceCheck(
                name="redis",
                status="healthy",
                critical=True,
                message="Redis connection successful",
                latency_ms=round(latency_ms, 2),
            )
        except Exception as exc:
            return ServiceCheck(
                name="redis",
                status="unhealthy",
                critical=True,
                message=str(exc),
            )
        finally:
            if client is not None:
                await client.close()

    async def check_tavily(self) -> ServiceCheck:
        """Report Tavily configuration status without making network calls."""
        api_key = os.getenv("TAVILY_API_KEY", "")
        if not api_key:
            return ServiceCheck(
                name="tavily",
                status="unconfigured",
                critical=False,
                message="TAVILY_API_KEY is not set",
            )

        return ServiceCheck(
            name="tavily",
            status="healthy",
            critical=False,
            message="Tavily API key configured",
        )

    async def get_worker_status(self) -> ServiceCheck:
        """Summarize worker heartbeats from Redis."""
        client = None
        worker_details: list[dict[str, Any]] = []
        stale_ids: list[str] = []

        try:
            client = await self._create_redis_client()
            worker_ids = sorted(await client.smembers(self.WORKER_REGISTRY_KEY))

            for worker_id in worker_ids:
                payload = await client.hgetall(f"{self.WORKER_KEY_PREFIX}{worker_id}")
                if not payload:
                    stale_ids.append(worker_id)
                    continue
                worker_details.append(payload)

            if stale_ids:
                await client.srem(self.WORKER_REGISTRY_KEY, *stale_ids)

            if not worker_details:
                return ServiceCheck(
                    name="workers",
                    status="degraded",
                    critical=False,
                    message="No active workers registered",
                    details={"count": 0},
                )

            return ServiceCheck(
                name="workers",
                status="healthy",
                critical=False,
                message="Active workers detected",
                details={"count": len(worker_details), "workers": worker_details},
            )
        except Exception as exc:
            return ServiceCheck(
                name="workers",
                status="unknown",
                critical=False,
                message=str(exc),
            )
        finally:
            if client is not None:
                await client.close()

    async def collect_startup_report(self, service_name: str) -> StartupReport:
        """Collect critical startup checks for a service."""
        checks = {
            "environment": await self.check_environment_variables(),
            "configuration": self.check_configuration(),
            "database": await self.check_database(),
            "redis": await self.check_redis(),
        }
        return StartupReport(service_name=service_name, checks=checks)

    async def collect_health_report(self, service_name: str, include_workers: bool = True) -> StartupReport:
        """Collect runtime health checks for API responses."""
        checks = {
            "configuration": self.check_configuration(),
            "database": await self.check_database(),
            "redis": await self.check_redis(),
            "tavily": await self.check_tavily(),
        }
        if include_workers:
            checks["workers"] = await self.get_worker_status()
        return StartupReport(service_name=service_name, checks=checks)

    async def ensure_startup_ready(self, service_name: str) -> StartupReport:
        """Run startup checks and raise if any critical dependency is unavailable."""
        report = await self.collect_startup_report(service_name)
        if not report.is_healthy:
            logger.error("startup_checks_failed", service=service_name, report=report.to_dict())
            raise StartupCheckError(report)

        logger.info("startup_checks_passed", service=service_name)
        return report

    async def initialize_api(self) -> StartupReport:
        """Validate dependencies and initialize shared API resources."""
        report = await self.ensure_startup_ready("api")
        await rate_limit_guard.connect()
        return report

    async def shutdown_api(self) -> None:
        """Close shared API resources."""
        errors: list[str] = []

        try:
            await db_repository.close()
            logger.info("database_connections_closed")
        except Exception as exc:
            errors.append(f"database: {exc}")
            logger.error("database_close_error", error=str(exc))

        try:
            await rate_limit_guard.close()
            logger.info("rate_limiter_closed")
        except Exception as exc:
            errors.append(f"rate_limiter: {exc}")
            logger.error("rate_limiter_close_error", error=str(exc))

        try:
            await close_redis_pool()
            logger.info("redis_pool_closed")
        except Exception as exc:
            errors.append(f"redis_pool: {exc}")
            logger.error("redis_pool_close_error", error=str(exc))

        if errors:
            raise RuntimeError("; ".join(errors))

    async def prepare_worker(self, worker_id: str, pid: int) -> StartupReport:
        """Validate dependencies and register a worker heartbeat."""
        report = await self.ensure_startup_ready("worker")
        await self.register_worker(worker_id, pid)
        return report

    async def register_worker(self, worker_id: str, pid: int) -> None:
        """Register a worker in Redis so health endpoints can see it."""
        client = await self._create_redis_client()
        worker_key = f"{self.WORKER_KEY_PREFIX}{worker_id}"
        now = datetime.utcnow().isoformat()
        try:
            await client.sadd(self.WORKER_REGISTRY_KEY, worker_id)
            await client.hset(
                worker_key,
                mapping={
                    "worker_id": worker_id,
                    "pid": str(pid),
                    "status": "starting",
                    "started_at": now,
                    "last_seen": now,
                    "active_jobs": "0",
                },
            )
            await client.expire(worker_key, config.worker_heartbeat_ttl_seconds)
        finally:
            await client.close()

    async def heartbeat_worker(self, worker_id: str, active_jobs: int) -> None:
        """Refresh worker heartbeat in Redis."""
        client = await self._create_redis_client()
        worker_key = f"{self.WORKER_KEY_PREFIX}{worker_id}"
        now = datetime.utcnow().isoformat()
        try:
            await client.hset(
                worker_key,
                mapping={
                    "status": "healthy",
                    "last_seen": now,
                    "active_jobs": str(active_jobs),
                },
            )
            await client.expire(worker_key, config.worker_heartbeat_ttl_seconds)
        finally:
            await client.close()

    async def unregister_worker(self, worker_id: str, status: str = "stopped") -> None:
        """Mark a worker as stopped and remove it from the registry."""
        client = await self._create_redis_client()
        worker_key = f"{self.WORKER_KEY_PREFIX}{worker_id}"
        try:
            await client.hset(
                worker_key,
                mapping={
                    "status": status,
                    "last_seen": datetime.utcnow().isoformat(),
                },
            )
            await client.expire(worker_key, 5)
            await client.srem(self.WORKER_REGISTRY_KEY, worker_id)
        finally:
            await client.close()

    async def start_worker_heartbeat(self, worker_id: str, active_jobs_getter) -> None:
        """Start background heartbeat updates for a worker."""
        if worker_id in self._worker_tasks:
            return

        async def _loop() -> None:
            while True:
                await self.heartbeat_worker(worker_id, active_jobs_getter())
                await asyncio.sleep(config.worker_heartbeat_interval_seconds)

        self._worker_tasks[worker_id] = asyncio.create_task(_loop())

    async def stop_worker_heartbeat(self, worker_id: str) -> None:
        """Stop background heartbeat updates for a worker."""
        task = self._worker_tasks.pop(worker_id, None)
        if task is None:
            return

        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def shutdown_worker(self, worker_id: str) -> None:
        """Close worker resources and unregister it."""
        await self.stop_worker_heartbeat(worker_id)
        await self.unregister_worker(worker_id)
        await task_queue.close()
        await db_repository.close()
        await close_redis_pool()

    def uptime(self) -> timedelta:
        """Return process uptime."""
        return datetime.utcnow() - self.started_at


runtime_manager = RuntimeManager()


async def run_startup_checks(service_name: str = "api") -> bool:
    """Compatibility wrapper for older call sites."""
    await runtime_manager.ensure_startup_ready(service_name)
    return True
