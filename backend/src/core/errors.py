"""Centralized error handling for frontend-safe API responses."""

import functools
import os
from datetime import datetime
from enum import Enum
from typing import Any, Callable, TypeVar

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.exc import ProgrammingError, SQLAlchemyError

from src.config.logging_config import get_logger

logger = get_logger(__name__)

# Type variable for generic function wrapping
F = TypeVar("F", bound=Callable[..., Any])


class ErrorCode(str, Enum):
    """Standardized error codes for API responses."""
    
    # Client errors (4xx)
    VALIDATION_ERROR = "VALIDATION_ERROR"
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    NOT_FOUND = "NOT_FOUND"
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    
    # Server errors (5xx)
    INTERNAL_ERROR = "INTERNAL_ERROR"
    DATABASE_ERROR = "DATABASE_ERROR"
    EXTERNAL_SERVICE_ERROR = "EXTERNAL_SERVICE_ERROR"
    AGENT_EXECUTION_ERROR = "AGENT_EXECUTION_ERROR"
    PIPELINE_ERROR = "PIPELINE_ERROR"
    
    # Business logic errors
    BLOG_GENERATION_FAILED = "BLOG_GENERATION_FAILED"
    RESEARCH_FAILED = "RESEARCH_FAILED"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"


class ErrorResponse(BaseModel):
    """Standardized error response model."""
    
    success: bool = False
    error_code: str
    message: str
    request_id: str | None = None
    timestamp: str


# Custom Exception Classes

class BlogifyError(Exception):
    """Base exception for all Blogify errors."""
    
    def __init__(
        self, 
        message: str, 
        error_code: ErrorCode = ErrorCode.INTERNAL_ERROR,
        status_code: int = 500,
        details: dict | None = None
    ):
        self.message = message
        self.error_code = error_code
        self.status_code = status_code
        self.details = details or {}
        super().__init__(message)


class ValidationError(BlogifyError):
    """Raised for input validation failures."""
    
    def __init__(self, message: str, details: dict | None = None):
        super().__init__(
            message=message,
            error_code=ErrorCode.VALIDATION_ERROR,
            status_code=400,
            details=details
        )


class RateLimitError(BlogifyError):
    """Raised when rate limits are exceeded."""
    
    def __init__(self, message: str = "Rate limit exceeded", details: dict | None = None):
        super().__init__(
            message=message,
            error_code=ErrorCode.RATE_LIMIT_EXCEEDED,
            status_code=429,
            details=details
        )


class BudgetExceededError(BlogifyError):
    """Raised when budget limits are exceeded."""
    
    def __init__(self, message: str = "Budget limit exceeded", details: dict | None = None):
        super().__init__(
            message=message,
            error_code=ErrorCode.BUDGET_EXCEEDED,
            status_code=429,
            details=details
        )


class NotFoundError(BlogifyError):
    """Raised when a resource is not found."""
    
    def __init__(self, message: str = "Resource not found", details: dict | None = None):
        super().__init__(
            message=message,
            error_code=ErrorCode.NOT_FOUND,
            status_code=404,
            details=details
        )


class DatabaseError(BlogifyError):
    """Raised for database operation failures."""
    
    def __init__(self, message: str = "Database operation failed", details: dict | None = None):
        super().__init__(
            message=message,
            error_code=ErrorCode.DATABASE_ERROR,
            status_code=500,
            details=details
        )


class ExternalServiceError(BlogifyError):
    """Raised when external service calls fail (Tavily, etc.)."""
    
    def __init__(self, message: str, service: str, details: dict | None = None):
        super().__init__(
            message=message,
            error_code=ErrorCode.EXTERNAL_SERVICE_ERROR,
            status_code=502,
            details={"service": service, **(details or {})}
        )


class AgentExecutionError(BlogifyError):
    """Raised when ADK agent execution fails."""
    
    def __init__(self, message: str, agent_name: str, details: dict | None = None):
        super().__init__(
            message=message,
            error_code=ErrorCode.AGENT_EXECUTION_ERROR,
            status_code=500,
            details={"agent": agent_name, **(details or {})}
        )


class PipelineError(BlogifyError):
    """Raised for pipeline execution failures."""
    
    def __init__(self, message: str, stage: str, details: dict | None = None):
        super().__init__(
            message=message,
            error_code=ErrorCode.PIPELINE_ERROR,
            status_code=500,
            details={"stage": stage, **(details or {})}
        )


# Environment-aware error formatting

def is_production() -> bool:
    """Check if running in production environment."""
    env = os.getenv("ENVIRONMENT", "dev").lower()
    return env in ("prod", "production")


def is_staging() -> bool:
    """Check if running in staging environment."""
    env = os.getenv("ENVIRONMENT", "dev").lower()
    return env in ("stage", "staging")


def _status_to_error_code(status_code: int) -> ErrorCode:
    if status_code == 400:
        return ErrorCode.VALIDATION_ERROR
    if status_code == 401:
        return ErrorCode.UNAUTHORIZED
    if status_code == 403:
        return ErrorCode.FORBIDDEN
    if status_code == 404:
        return ErrorCode.NOT_FOUND
    if status_code == 429:
        return ErrorCode.RATE_LIMIT_EXCEEDED
    if status_code >= 500:
        return ErrorCode.INTERNAL_ERROR
    return ErrorCode.VALIDATION_ERROR


def _database_message(error: SQLAlchemyError) -> str:
    message = str(error).lower()
    if "undefinedtable" in message or "does not exist" in message:
        return "Database schema is not up to date. Run migrations and try again."
    return "A database error occurred. Please verify setup and try again."


def format_error_response(
    error: Exception,
    request_id: str | None = None,
) -> ErrorResponse:
    """Format an exception into a safe, structured public response."""
    
    timestamp = datetime.utcnow().isoformat()
    
    if isinstance(error, BlogifyError):
        return ErrorResponse(
            error_code=error.error_code.value,
            message=error.message,
            request_id=request_id,
            timestamp=timestamp
        )
    
    elif isinstance(error, HTTPException):
        code = _status_to_error_code(error.status_code)
        return ErrorResponse(
            error_code=code.value,
            message=str(error.detail),
            request_id=request_id,
            timestamp=timestamp
        )

    elif isinstance(error, SQLAlchemyError):
        return ErrorResponse(
            error_code=ErrorCode.DATABASE_ERROR.value,
            message=_database_message(error),
            request_id=request_id,
            timestamp=timestamp,
        )
    
    else:
        return ErrorResponse(
            error_code=ErrorCode.INTERNAL_ERROR.value,
            message="A server error occurred. Please try again.",
            request_id=request_id,
            timestamp=timestamp
        )


# Error handling decorators

def handle_errors(func: F) -> F:
    """
    Decorator for async route handlers with centralized error handling.
    
    Usage:
        @router.get("/example")
        @handle_errors
        async def example_endpoint():
            ...
    """
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        
        except BlogifyError as e:
            logger.error(
                "blogify_error",
                error_code=e.error_code.value,
                message=e.message,
                details=e.details
            )
            raise HTTPException(status_code=e.status_code, detail=e.message)
        
        except HTTPException:
            raise
        
        except Exception as e:
            logger.exception("unexpected_error", error=str(e))
            
            if is_production():
                raise HTTPException(status_code=500, detail="Internal server error")
            else:
                raise HTTPException(status_code=500, detail=str(e))
    
    return wrapper  # type: ignore


def handle_service_errors(func: F) -> F:
    """
    Decorator for service layer methods with error transformation.
    
    Transforms low-level exceptions into appropriate BlogifyError types.
    """
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        
        except BlogifyError:
            raise
        
        except ValueError as e:
            raise ValidationError(str(e))
        
        except Exception as e:
            logger.exception("service_error", error=str(e), func=func.__name__)
            raise BlogifyError(
                message=f"Service error: {str(e)}" if not is_production() else "Service error",
                error_code=ErrorCode.INTERNAL_ERROR
            )
    
    return wrapper  # type: ignore


# FastAPI exception handlers

async def blogify_exception_handler(request: Request, exc: BlogifyError) -> JSONResponse:
    """FastAPI exception handler for BlogifyError."""
    request_id = getattr(request.state, "request_id", None)
    
    logger.error(
        "request_error",
        request_id=request_id,
        error_code=exc.error_code.value,
        message=exc.message,
        path=request.url.path
    )
    
    response = format_error_response(exc, request_id=request_id)
    
    return JSONResponse(
        status_code=exc.status_code,
        content=response.model_dump(exclude_none=True)
    )


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """FastAPI exception handler for HTTPException."""
    request_id = getattr(request.state, "request_id", None)
    response = format_error_response(exc, request_id=request_id)
    logger.warning(
        "http_exception",
        request_id=request_id,
        status_code=exc.status_code,
        detail=str(exc.detail),
        path=request.url.path,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=response.model_dump(exclude_none=True),
    )


async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    """FastAPI exception handler for request validation failures."""
    request_id = getattr(request.state, "request_id", None)
    logger.warning(
        "request_validation_failed",
        request_id=request_id,
        errors=exc.errors(),
        path=request.url.path,
    )
    response = ErrorResponse(
        error_code=ErrorCode.VALIDATION_ERROR.value,
        message="Invalid request payload.",
        request_id=request_id,
        timestamp=datetime.utcnow().isoformat(),
    )
    return JSONResponse(
        status_code=422,
        content=response.model_dump(exclude_none=True),
    )


async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """FastAPI exception handler for unhandled exceptions."""
    request_id = getattr(request.state, "request_id", None)
    
    logger.exception(
        "unhandled_exception",
        request_id=request_id,
        error=str(exc),
        path=request.url.path
    )
    
    response = format_error_response(exc, request_id=request_id)
    
    status_code = 500
    if isinstance(exc, SQLAlchemyError):
        status_code = 500
    return JSONResponse(status_code=status_code, content=response.model_dump(exclude_none=True))


def register_exception_handlers(app):
    """Register all exception handlers with FastAPI app."""
    app.add_exception_handler(BlogifyError, blogify_exception_handler)
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, generic_exception_handler)


# Utility functions

def safe_execute(
    func: Callable,
    error_message: str = "Operation failed",
    error_code: ErrorCode = ErrorCode.INTERNAL_ERROR,
    **kwargs
):
    """
    Execute a function with error wrapping.
    
    Usage:
        result = await safe_execute(
            some_async_function,
            error_message="Failed to process data",
            arg1=value1
        )
    """
    async def _execute():
        try:
            if asyncio.iscoroutinefunction(func):
                return await func(**kwargs)
            else:
                return func(**kwargs)
        except BlogifyError:
            raise
        except Exception as e:
            logger.error("safe_execute_failed", error=str(e), func=func.__name__)
            raise BlogifyError(
                message=error_message,
                error_code=error_code,
                details={"original_error": str(e)} if not is_production() else None
            )
    
    return _execute()


import asyncio  # Import at end to avoid circular issues
