"""FastAPI main application for Blogify V1."""

import os
from dotenv import load_dotenv

env = os.getenv("ENVIRONMENT", "dev")
load_dotenv(f".env.{env}")

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.config.env_config import config
from src.config.logging_config import get_logger, setup_logging
from src.core.errors import register_exception_handlers
from src.api.auth import AuthMiddleware
from src.api.routes import health
from src.api.routes.auth_routes import router as auth_router
from src.api.routes.blog_routes import router as blog_router

setup_logging(
    config.log_level,
    log_format=config.log_format,
    mask_secrets=config.mask_secrets_in_logs,
)
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.cors_origins,
    allow_credentials=config.cors_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(AuthMiddleware, required=False)

register_exception_handlers(app)

app.include_router(health.router, prefix="/api", tags=["Health"])
app.include_router(health.router, prefix=API_PREFIX, tags=["Health"])
app.include_router(auth_router, prefix=API_PREFIX, tags=["Auth"])
app.include_router(blog_router, prefix=API_PREFIX, tags=["Blogs"])


@app.get("/", tags=["Root"])
async def root():
    return {
        "service": "Blogify AI API",
        "version": API_VERSION,
        "environment": config.environment,
        "status": "running",
        "docs": "/docs",
    }