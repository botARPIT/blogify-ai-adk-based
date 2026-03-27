"""FastAPI main application with canonical blog session APIs."""

import os
import signal
import asyncio
from dotenv import load_dotenv

# Load environment file before any other imports
env = os.getenv("ENVIRONMENT", "dev")
load_dotenv(f".env.{env}")

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi

from src.api.auth import require_authenticated_user
from src.api.middleware import setup_middleware
from src.config.env_config import config
from src.config.logging_config import get_logger, setup_logging
from src.core.errors import register_exception_handlers
from src.core.startup import StartupCheckError, runtime_manager
from src.monitoring.metrics import daily_cost_usd, metrics_endpoint
from src.monitoring.tracing import init_tracing, instrument_app
from src.models.repository import db_repository
from src.models.repositories.blog_session_repository import BlogSessionRepository
from src.models.repositories.budget_repository import BudgetRepository
from src.models.repositories.auth_user_repository import AuthUserRepository
from src.services.budget_service import BudgetService
from src.services.local_auth_service import LocalAuthService

# Setup logging
setup_logging(
    config.log_level,
    log_format=config.log_format,
    mask_secrets=config.mask_secrets_in_logs,
)
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
    
    try:
        await runtime_manager.shutdown_api()
    except Exception as e:
        logger.error("graceful_shutdown_cleanup_error", error=str(e))
    
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

    try:
        await runtime_manager.initialize_api()
    except StartupCheckError as exc:
        logger.error("application_startup_failed", report=exc.report.to_dict())
        try:
            await runtime_manager.shutdown_api()
        except Exception as cleanup_error:
            logger.error("startup_failure_cleanup_error", error=str(cleanup_error))
        raise RuntimeError(str(exc)) from exc

    logger.info("database_schema_expected_via_alembic")

    try:
        async with db_repository.async_session() as session:
            async with session.begin():
                await LocalAuthService().ensure_seed_user(AuthUserRepository(session))
        logger.info("local_auth_seed_checked")
    except Exception as exc:
        logger.warning("local_auth_seed_skipped", error=str(exc))

    # Initialize distributed tracing
    init_tracing(service_name="blogify-api")
    instrument_app(app)

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
## Canonical AI Blog Generation System

Generate and review blog sessions using Google ADK agents with:
- **Intent Classification**
- **Outline Generation**
- **Human outline review**
- **Research and drafting**
- **Final human review**

### Features
- Budget enforcement and session tracking
- Human-in-the-loop checkpoints
- Real-time canonical session status
- Local cookie-based authentication
- In-app notifications for async workflow transitions
- Internal service adapter routes

### Authentication
Browser clients authenticate with local email/password login and HTTP-only cookies.
Internal service routes continue to use the `X-Internal-Api-Key` header.
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

# Health routes are always available
from src.api.routes import health
app.include_router(health.router, prefix="/api", tags=["Health"])  # Health at /api for backward compat
app.include_router(health.router, prefix=API_PREFIX, tags=["Health"])

if config.enable_canonical_routes:
    from src.api.routes.admin_service_clients import router as admin_service_clients_router
    from src.api.routes.auth_local import router as auth_router
    from src.api.routes.canonical import canonical_router, internal_router
    from src.api.routes.notifications import router as notification_router

    app.include_router(auth_router, tags=["Auth"])
    app.include_router(canonical_router, tags=["Blog Generation"])
    app.include_router(notification_router, tags=["Notifications"])
    app.include_router(internal_router, tags=["Internal Service"])
    if getattr(config, "enable_admin_routes", False):
        app.include_router(admin_service_clients_router, tags=["Admin"])
    logger.info("canonical_routes_enabled")
else:
    logger.info("canonical_routes_disabled")


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
async def metrics(request: Request, x_internal_api_key: str | None = None):
    """
    Prometheus metrics endpoint.
    
    Returns metrics in Prometheus format for scraping.
    """
    if not config.enable_metrics:
        return {"error": "Metrics disabled"}

    if not config.metrics_public:
        from src.api.routes.canonical import require_internal_service_client

        await require_internal_service_client(request, x_internal_api_key)

    return await metrics_endpoint()


@app.get(f"{API_PREFIX}/costs", tags=["Monitoring"])
async def get_cost_summary(request: Request):
    """
    Return the current authenticated user's canonical budget snapshot.
    """
    current_user = require_authenticated_user(request)
    from datetime import datetime as _dt
    from src.api.routes.canonical import _resolve_standalone_budget

    tenant_id, end_user_id = await _resolve_standalone_budget(current_user.user_id)

    try:
        async with db_repository.async_session() as session:
            budget_service = BudgetService(
                budget_repo=BudgetRepository(session),
                session_repo=BlogSessionRepository(session),
            )
            snapshot = await budget_service.get_snapshot(tenant_id, end_user_id)
            daily_cost_usd.labels(scope="user").set(snapshot.daily_spent_usd)

        return {
            "user_id": current_user.user_id,
            "date": _dt.utcnow().date().isoformat(),
            "daily_cost_usd": snapshot.daily_spent_usd,
            "daily_spent_tokens": snapshot.daily_spent_tokens,
            "daily_limit_usd": snapshot.daily_limit_usd,
            "daily_limit_tokens": snapshot.daily_limit_tokens,
            "active_sessions": snapshot.active_sessions,
            "max_concurrent_sessions": snapshot.max_concurrent_sessions,
            "remaining_revision_iterations": snapshot.remaining_revision_iterations,
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
    if config.environment == "prod":
        raise HTTPException(status_code=404, detail="Not found")

    return {
        "version": API_VERSION,
        "environment": config.environment,
        "python_version": "3.11",
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
