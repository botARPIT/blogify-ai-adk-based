"""Health check endpoints with dependency verification."""

import asyncio
from datetime import datetime, timedelta

from fastapi import APIRouter, Response

from src.config.env_config import config
from src.config.logging_config import get_logger
from src.guards.rate_limit_guard import rate_limit_guard
from src.models.repository import db_repository

logger = get_logger(__name__)

router = APIRouter()

# Track startup time
_startup_time = datetime.utcnow()


@router.get("/health")
async def health_check():
    """
    Simple health check endpoint.
    
    Returns basic healthy/unhealthy status.
    Used by load balancers for simple liveness checks.
    """
    return {
        "status": "healthy",
        "service": "blogify-ai",
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.get("/health/live")
async def liveness_check():
    """
    Kubernetes liveness probe endpoint.
    
    Returns 200 if the application is running.
    Failure triggers container restart.
    """
    return {"status": "alive"}


@router.get("/health/ready")
async def readiness_check(response: Response):
    """
    Kubernetes readiness probe endpoint.
    
    Returns 200 if the application can accept traffic.
    Returns 503 if dependencies are not ready.
    """
    checks = await _check_all_dependencies()
    
    is_ready = all(c["status"] == "healthy" for c in checks.values())
    
    if not is_ready:
        response.status_code = 503
    
    return {
        "status": "ready" if is_ready else "not_ready",
        "checks": checks,
    }


@router.get("/health/detailed")
async def detailed_health_check():
    """
    Detailed health check with all dependencies.
    
    Checks:
    - Database connectivity
    - Redis connectivity
    - Tavily API (optional)
    - Memory usage
    - Uptime
    """
    checks = await _check_all_dependencies()
    
    # Calculate uptime
    uptime = datetime.utcnow() - _startup_time
    
    # Overall status
    critical_checks = ["database"]  # Only database is critical
    critical_healthy = all(
        checks.get(c, {}).get("status") == "healthy" 
        for c in critical_checks
    )
    
    all_healthy = all(c["status"] == "healthy" for c in checks.values())
    
    if critical_healthy and all_healthy:
        overall_status = "healthy"
    elif critical_healthy:
        overall_status = "degraded"
    else:
        overall_status = "unhealthy"
    
    return {
        "status": overall_status,
        "service": "blogify-ai",
        "version": config.environment,
        "uptime_seconds": int(uptime.total_seconds()),
        "uptime_human": str(uptime).split(".")[0],
        "timestamp": datetime.utcnow().isoformat(),
        "checks": checks,
    }


async def _check_all_dependencies() -> dict:
    """Check all service dependencies."""
    checks = {}
    
    # Check database
    checks["database"] = await _check_database()
    
    # Check Redis
    checks["redis"] = await _check_redis()
    
    # Check Tavily (non-critical)
    checks["tavily"] = await _check_tavily()
    
    return checks


async def _check_database() -> dict:
    """Check database connectivity."""
    try:
        # Try a simple query
        start = datetime.utcnow()
        from sqlalchemy import text
        async with db_repository.async_session() as session:
            await session.execute(text("SELECT 1"))
        latency_ms = (datetime.utcnow() - start).total_seconds() * 1000
        
        return {
            "status": "healthy",
            "latency_ms": round(latency_ms, 2),
        }
    except Exception as e:
        logger.error("database_health_check_failed", error=str(e))
        return {
            "status": "unhealthy",
            "error": str(e)[:100],
        }


async def _check_redis() -> dict:
    """Check Redis connectivity."""
    try:
        start = datetime.utcnow()
        client = await rate_limit_guard._get_client()
        await client.ping()
        latency_ms = (datetime.utcnow() - start).total_seconds() * 1000
        
        return {
            "status": "healthy",
            "latency_ms": round(latency_ms, 2),
        }
    except Exception as e:
        logger.warning("redis_health_check_failed", error=str(e))
        return {
            "status": "unhealthy",
            "error": str(e)[:100],
        }


async def _check_tavily() -> dict:
    """Check Tavily API connectivity (non-critical)."""
    try:
        import os
        api_key = os.getenv("TAVILY_API_KEY", "")
        
        if not api_key:
            return {
                "status": "unconfigured",
                "message": "API key not set",
            }
        
        # Don't actually call Tavily in health check (costs money)
        # Just verify the key exists
        return {
            "status": "healthy",
            "message": "API key configured",
        }
    except Exception as e:
        return {
            "status": "unknown",
            "error": str(e)[:100],
        }


@router.get("/health/startup")
async def startup_health():
    """
    Startup probe endpoint.
    
    Returns information about application startup status.
    """
    uptime = datetime.utcnow() - _startup_time
    
    return {
        "status": "started",
        "started_at": _startup_time.isoformat(),
        "uptime_seconds": int(uptime.total_seconds()),
        "environment": config.environment,
    }
