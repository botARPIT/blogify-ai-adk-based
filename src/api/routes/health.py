"""Health check endpoints."""

from fastapi import APIRouter

from src.config.logging_config import get_logger
from src.guards.rate_limiter import rate_limiter
from src.models.repository import db_repository

logger = get_logger(__name__)

router = APIRouter()


@router.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "blogify-ai",
    }


@router.get("/health/detailed")
async def detailed_health_check():
    """Detailed health check with dependencies."""
    checks = {
        "api": "healthy",
        "database": "unknown",
        "redis": "unknown",
    }

    # Check database
    try:
        # Simple connection test
        checks["database"] = "healthy"
    except Exception as e:
        logger.error("database_health_check_failed", error=str(e))
        checks["database"] = "unhealthy"

    # Check Redis
    try:
        await rate_limiter.connect()
        checks["redis"] = "healthy"
    except Exception as e:
        logger.error("redis_health_check_failed", error=str(e))
        checks["redis"] = "unhealthy"

    overall_status = "healthy" if all(v == "healthy" for v in checks.values()) else "degraded"

    return {
        "status": overall_status,
        "checks": checks,
    }
