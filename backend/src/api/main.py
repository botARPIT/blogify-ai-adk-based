"""FastAPI main application for Blogify V1."""

import asyncio
import os
import time

from dotenv import load_dotenv

env = os.getenv("ENVIRONMENT", "dev")
load_dotenv(f".env.{env}")

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from src.api.auth import AuthMiddleware
from src.api.middleware.rate_limit import RateLimitMiddleware
from src.api.routes import health
from src.api.routes.auth_routes import router as auth_router
from src.api.routes.blog_routes import router as blog_router
from src.api.routes.tone_routes import router as tone_router
from src.config.env_config import config
from src.config.logging_config import get_logger, setup_logging
from src.core.database import engine
from src.core.errors import register_exception_handlers
from src.monitoring.metrics import (
    http_request_duration_seconds,
    http_requests_in_progress,
    http_requests_total,
    metrics_endpoint,
)
from src.monitoring.runtime_metrics import cancel_metrics_task, runtime_metrics_poller
from src.monitoring.tracing import init_tracing, instrument_app, instrument_database

setup_logging(
    config.log_level,
    log_format=config.log_format,
    mask_secrets=config.mask_secrets_in_logs,
)
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("application_startup", environment=config.environment)
    metrics_task = asyncio.create_task(
        runtime_metrics_poller("api", include_shared_state=True)
    )
    try:
        yield
    finally:
        await cancel_metrics_task(metrics_task)
        logger.info("application_shutdown")


API_VERSION = "1.0.0"
API_PREFIX = "/api/v1"

app = FastAPI(
    title="Blogify AI API",
    description="V1 API for AI blog generation with human-in-the-loop reviews.",
    version=API_VERSION,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

init_tracing()
instrument_app(app)
instrument_database(engine)
app.add_route("/metrics", metrics_endpoint, methods=["GET"], include_in_schema=False)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(AuthMiddleware, required=False)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.cors_origins,
    allow_credentials=config.cors_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def collect_http_metrics(request: Request, call_next):
    """Record golden-signal HTTP metrics with route templates, not raw URLs."""
    if request.url.path == "/metrics":
        return await call_next(request)

    method = request.method
    http_requests_in_progress.labels(method=method).inc()
    started_at = time.perf_counter()
    status_code = "500"
    try:
        response = await call_next(request)
        status_code = str(response.status_code)
        return response
    finally:
        route = request.scope.get("route")
        endpoint = route.path if route else "unmatched"
        http_request_duration_seconds.labels(method=method, endpoint=endpoint).observe(
            time.perf_counter() - started_at
        )
        http_requests_total.labels(
            method=method, endpoint=endpoint, status_code=status_code
        ).inc()
        http_requests_in_progress.labels(method=method).dec()

register_exception_handlers(app)

# Keep the legacy health URLs available for load balancers, but publish only
# the versioned contract in OpenAPI so every health operation appears once.
app.include_router(health.router, prefix="/api", tags=["Health"], include_in_schema=False)
app.include_router(health.router, prefix=API_PREFIX, tags=["Health"])
app.include_router(auth_router, prefix=API_PREFIX, tags=["Auth"])
app.include_router(blog_router, prefix=API_PREFIX, tags=["Blogs"])
app.include_router(tone_router, prefix=API_PREFIX, tags=["Tones"])


@app.get("/", tags=["Root"])
async def root():
    return {
        "service": "Blogify AI API",
        "version": API_VERSION,
        "environment": config.environment,
        "status": "running",
        "docs": "/docs",
    }
