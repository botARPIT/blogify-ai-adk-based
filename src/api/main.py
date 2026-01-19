"""FastAPI main application with production-grade features.

Features:
- API versioning (v1)
- Health checks with dependency verification
- Graceful shutdown
- Request ID tracking
- Rate limiting with headers
- OpenAPI documentation
- Cost tracking endpoint
"""

import os
import signal
import asyncio
from datetime import datetime
from dotenv import load_dotenv

# Load environment file before any other imports
env = os.getenv("ENVIRONMENT", "dev")
load_dotenv(f".env.{env}")

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi

from src.api.routes import blog, chat, health
from src.api.middleware import setup_middleware
from src.config.env_config import config
from src.config.logging_config import get_logger, setup_logging
from src.core.errors import register_exception_handlers
from src.core.session_store import redis_session_service
from src.guards.rate_limit_guard import rate_limit_guard
from src.models.repository import db_repository
from src.monitoring.metrics import metrics_endpoint
from src.monitoring.tracing import init_tracing, instrument_app

# Setup logging
setup_logging(config.log_level)
logger = get_logger(__name__)


# Semaphore for concurrent request limiting (scalability)
request_semaphore = asyncio.Semaphore(config.max_concurrent_requests)

# Graceful shutdown flag
shutdown_event = asyncio.Event()


async def graceful_shutdown():
    """Handle graceful shutdown with connection draining."""
    logger.info("graceful_shutdown_initiated")
    
    # Set shutdown flag
    shutdown_event.set()
    
    # Wait for in-flight requests to complete (max 30 seconds)
    drain_timeout = 30
    logger.info(f"draining_connections", timeout_seconds=drain_timeout)
    
    # Close database connections
    try:
        await db_repository.close()
        logger.info("database_connections_closed")
    except Exception as e:
        logger.error("database_close_error", error=str(e))
    
    # Close rate limiter
    try:
        await rate_limit_guard.close()
        logger.info("rate_limiter_closed")
    except Exception as e:
        logger.error("rate_limiter_close_error", error=str(e))
    
    logger.info("graceful_shutdown_complete")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup/shutdown."""
    # Startup
    logger.info(
        "application_startup",
        environment=config.environment,
        workers=config.api_workers,
        version=API_VERSION,
    )

    # Run dependency checks
    from src.core.startup import run_startup_checks

    startup_ok = await run_startup_checks()
    if not startup_ok:
        logger.error("Startup checks failed - terminating")
        raise RuntimeError("Startup checks failed")

    logger.info("✅ All startup checks passed - initializing services...")

    # Initialize database
    await db_repository.create_tables()

    # Initialize rate limiter
    await rate_limit_guard.connect()

    # Initialize distributed tracing
    init_tracing(service_name="blogify-api")

    # Register signal handlers for graceful shutdown
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(graceful_shutdown()))

    logger.info("🚀 Application ready to accept requests")


    yield

    # Shutdown
    await graceful_shutdown()


# API Version
API_VERSION = "1.0.0"
API_PREFIX = "/api/v1"

# Create FastAPI app with enhanced OpenAPI
app = FastAPI(
    title="Blogify AI API",
    description="""
## Production-grade AI Blog Generation System

Generate high-quality blog posts using Google ADK agents with:
- **Intent Classification**: Validates and clarifies blog topics
- **Outline Generation**: Creates structured blog outlines
- **Research**: Gathers sources via Tavily API
- **Content Writing**: Generates full blog content with citations

### Features
- Human-in-the-Loop (HITL) approval workflow
- Rate limiting and budget enforcement
- Cost tracking per blog generation
- Real-time generation status

### Authentication
This API expects authentication to be handled by an external auth service.
Include the `Authorization` header with your bearer token.
    """,
    version=API_VERSION,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    contact={
        "name": "Blogify AI Support",
        "email": "support@blogify.ai",
    },
    license_info={
        "name": "Proprietary",
    },
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.cors_origins,
    allow_credentials=config.cors_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID", "X-Response-Time", "X-RateLimit-Limit", "X-RateLimit-Remaining"],
)

# Add custom middleware
setup_middleware(app)

# Register exception handlers
register_exception_handlers(app)

# Include routers with v1 prefix
app.include_router(health.router, prefix="/api", tags=["Health"])  # Health at /api for backward compat
app.include_router(health.router, prefix=API_PREFIX, tags=["Health"])
app.include_router(chat.router, prefix=API_PREFIX, tags=["Chat"])
app.include_router(blog.router, prefix=API_PREFIX, tags=["Blog"])

# Keep legacy routes for backward compatibility
app.include_router(blog.router, prefix="/api", tags=["Blog (Legacy)"], include_in_schema=False)
app.include_router(chat.router, prefix="/api", tags=["Chat (Legacy)"], include_in_schema=False)


@app.get("/", tags=["Root"])
async def root():
    """
    Root endpoint with API information.
    
    Returns API version, status, and available endpoints.
    """
    return {
        "service": "Blogify AI API",
        "version": API_VERSION,
        "environment": config.environment,
        "status": "running",
        "api_prefix": API_PREFIX,
        "docs": "/docs",
        "health": "/api/health",
        "metrics": "/metrics",
    }


@app.get("/metrics", tags=["Monitoring"])
async def metrics():
    """
    Prometheus metrics endpoint.
    
    Returns metrics in Prometheus format for scraping.
    """
    if config.enable_metrics:
        return await metrics_endpoint()
    return {"error": "Metrics disabled"}


@app.get(f"{API_PREFIX}/costs", tags=["Monitoring"])
async def get_cost_summary(user_id: str | None = None):
    """
    Get cost tracking summary.
    
    - **user_id**: Optional user ID to filter costs
    
    Returns:
    - Daily cost totals
    - Per-user breakdown (if admin)
    - Cost by agent type
    """
    try:
        if user_id:
            daily_cost = await db_repository.get_user_daily_cost(user_id)
            blog_count = await db_repository.get_user_daily_blog_count(user_id)
            return {
                "user_id": user_id,
                "date": datetime.utcnow().date().isoformat(),
                "daily_cost_usd": daily_cost,
                "daily_blog_count": blog_count,
                "budget_limit_usd": config.per_user_daily_budget,
                "budget_remaining_usd": max(0, config.per_user_daily_budget - daily_cost),
            }
        else:
            # Global summary (admin only in production)
            return {
                "date": datetime.utcnow().date().isoformat(),
                "global_daily_budget_usd": config.global_daily_budget,
                "per_blog_budget_usd": config.per_blog_cost_budget,
                "per_user_daily_budget_usd": config.per_user_daily_budget,
                "message": "Provide user_id for per-user costs",
            }
    except Exception as e:
        logger.error("cost_summary_error", error=str(e))
        return {"error": "Failed to fetch cost summary"}


@app.get(f"{API_PREFIX}/system/info", tags=["System"])
async def system_info():
    """
    Get system information for debugging.
    
    Returns environment, version, and configuration info.
    """
    return {
        "version": API_VERSION,
        "environment": config.environment,
        "python_version": "3.10",
        "max_concurrent_requests": config.max_concurrent_requests,
        "rate_limits": {
            "blogs_per_day": config.rate_limit_blogs_per_day,
            "requests_per_minute": config.rate_limit_requests_per_minute,
        },
        "features": {
            "metrics_enabled": config.enable_metrics,
            "hitl_enabled": True,
            "research_enabled": True,
        }
    }


# Custom OpenAPI schema
def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    
    openapi_schema = get_openapi(
        title="Blogify AI API",
        version=API_VERSION,
        description=app.description,
        routes=app.routes,
    )
    
    # Add security scheme placeholder (actual auth handled externally)
    openapi_schema["components"]["securitySchemes"] = {
        "bearerAuth": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": "JWT token from external auth service"
        }
    }
    
    # Add server info
    openapi_schema["servers"] = [
        {"url": "/", "description": "Current server"},
        {"url": "https://api.blogify.ai", "description": "Production"},
    ]
    
    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi
