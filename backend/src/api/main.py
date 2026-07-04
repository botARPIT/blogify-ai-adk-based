"""FastAPI main application for Blogify V1."""

import os
import time
from collections.abc import Callable
from contextlib import asynccontextmanager

from dotenv import load_dotenv

env = os.getenv("ENVIRONMENT", "dev")
load_dotenv(f".env.{env}")

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.routing import Match

from src.api.auth import AuthMiddleware
from src.api.middleware.rate_limit import RateLimitMiddleware
from src.api.routes import health
from src.api.routes.auth_routes import router as auth_router
from src.api.routes.blog_routes import router as blog_router
from src.config.env_config import config
from src.config.logging_config import get_logger, setup_logging
from src.core.errors import register_exception_handlers
from src.monitoring import metrics_endpoint
from src.monitoring.metrics import http_request_duration_seconds, http_requests_total
from src.monitoring.tracing import init_tracing, instrument_app

setup_logging(
    config.log_level,
    log_format=config.log_format,
    mask_secrets=config.mask_secrets_in_logs,
)
logger = get_logger(__name__)


class PrometheusMiddleware(BaseHTTPMiddleware):
    """Record http_requests_total and http_request_duration_seconds for every request."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start = time.perf_counter()
        response = await call_next(request)
        elapsed = time.perf_counter() - start

        # Resolve route template (e.g. /api/v1/blogs/{session_id}) to avoid
        # high-cardinality metric labels from raw path IDs.
        endpoint = request.url.path
        for route in request.app.routes:
            match, _ = route.matches(request.scope)
            if match == Match.FULL:
                endpoint = getattr(route, "path", endpoint)
                break

        method = request.method
        status_code = str(response.status_code)

        http_requests_total.labels(
            method=method, endpoint=endpoint, status_code=status_code
        ).inc()
        http_request_duration_seconds.labels(
            method=method, endpoint=endpoint
        ).observe(elapsed)

        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_tracing(service_name="blogify-api")
    instrument_app(app)
    logger.info("application_startup", environment=config.environment)
    yield
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

# PrometheusMiddleware must be outermost (added last = executed first in Starlette)
app.add_middleware(PrometheusMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.cors_origins,
    allow_credentials=config.cors_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(AuthMiddleware, required=False)
app.add_middleware(RateLimitMiddleware)

register_exception_handlers(app)

app.include_router(health.router, prefix="/api", tags=["Health"])
app.include_router(health.router, prefix=API_PREFIX, tags=["Health"])
app.include_router(auth_router, prefix=API_PREFIX, tags=["Auth"])
app.include_router(blog_router, prefix=API_PREFIX, tags=["Blogs"])
app.get("/metrics", tags=["Metrics"])(metrics_endpoint)


@app.get("/", tags=["Root"])
async def root():
    return {
        "service": "Blogify AI API",
        "version": API_VERSION,
        "environment": config.environment,
        "status": "running",
        "docs": "/docs",
    }
