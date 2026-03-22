"""Health check endpoints backed by the centralized runtime manager."""

from datetime import datetime

from fastapi import APIRouter, Response

from src.config.env_config import config
from src.core.startup import runtime_manager

router = APIRouter()


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
    report = await runtime_manager.collect_health_report("api", include_workers=True)
    checks = report.to_dict()["checks"]
    is_ready = report.is_healthy
    
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
    report = await runtime_manager.collect_health_report("api", include_workers=True)
    uptime = runtime_manager.uptime()
    
    return {
        "status": report.status,
        "service": "blogify-ai",
        "version": config.environment,
        "uptime_seconds": int(uptime.total_seconds()),
        "uptime_human": str(uptime).split(".")[0],
        "timestamp": datetime.utcnow().isoformat(),
        "checks": report.to_dict()["checks"],
    }


@router.get("/health/startup")
async def startup_health():
    """
    Startup probe endpoint.
    
    Returns information about application startup status.
    """
    uptime = runtime_manager.uptime()
    
    return {
        "status": "started",
        "started_at": runtime_manager.started_at.isoformat(),
        "uptime_seconds": int(uptime.total_seconds()),
        "environment": config.environment,
    }
