"""FastAPI main application with environment-based configuration."""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.routes import blog, chat, health
from src.config.env_config import config
from src.config.logging_config import get_logger, setup_logging
from src.guards.rate_limiter import rate_limiter
from src.models.repository import db_repository
from src.monitoring.metrics import metrics_endpoint

# Setup logging
setup_logging(config.log_level)
logger = get_logger(__name__)

# Semaphore for concurrent request limiting
request_semaphore = asyncio.Semaphore(config.max_concurrent_requests)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup/shutdown."""
    # Startup
    logger.info(
        "application_startup",
        environment=config.environment,
        workers=config.api_workers,
    )

    # Initialize database
    await db_repository.create_tables()

    # Initialize rate limiter
    await rate_limiter.connect()

    yield

    # Shutdown
    logger.info("application_shutdown")
    await rate_limiter.close()


# Create FastAPI app
app = FastAPI(
    title="Blogify AI API",
    description="Production-grade blog generation system with Google ADK",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS middleware with environment-specific configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.cors_origins,
    allow_credentials=config.cors_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(health.router, prefix="/api", tags=["Health"])
app.include_router(chat.router, prefix="/api", tags=["Chat"])
app.include_router(blog.router, prefix="/api", tags=["Blog"])


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "service": "Blogify AI API",
        "version": "1.0.0",
        "environment": config.environment,
        "status": "running",
    }


@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint."""
    if config.enable_metrics:
        return await metrics_endpoint()
    return {"error": "Metrics disabled"}
