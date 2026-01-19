"""Request middleware for tracking, timing, and logging."""

import time
import uuid
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from src.config.logging_config import get_logger
from src.monitoring.metrics import http_requests_total, http_request_duration_seconds

logger = get_logger(__name__)


class RequestIDMiddleware(BaseHTTPMiddleware):
    """
    Middleware to add unique request ID to each request.
    
    The request ID is:
    - Generated if not provided in X-Request-ID header
    - Stored in request.state.request_id
    - Returned in X-Request-ID response header
    """
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Get or generate request ID
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        
        # Store in request state for access in handlers
        request.state.request_id = request_id
        
        # Process request
        response = await call_next(request)
        
        # Add request ID to response headers
        response.headers["X-Request-ID"] = request_id
        
        return response


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware to log all requests with timing information.
    
    Logs:
    - Request method, path, status code
    - Response time
    - Request ID
    """
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start_time = time.time()
        
        # Process request
        response = await call_next(request)
        
        # Calculate duration
        duration = time.time() - start_time
        duration_ms = duration * 1000
        
        # Get request ID
        request_id = getattr(request.state, "request_id", "unknown")
        
        # Log request
        logger.info(
            "http_request",
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=round(duration_ms, 2),
        )
        
        # Record Prometheus metrics
        try:
            http_requests_total.labels(
                method=request.method,
                endpoint=request.url.path,
                status_code=str(response.status_code)
            ).inc()
            
            http_request_duration_seconds.labels(
                method=request.method,
                endpoint=request.url.path
            ).observe(duration)
        except Exception:
            pass  # Don't fail request if metrics fail
        
        # Add timing header
        response.headers["X-Response-Time"] = f"{duration_ms:.2f}ms"
        
        return response


class RateLimitHeaderMiddleware(BaseHTTPMiddleware):
    """
    Middleware to add rate limit headers to responses.
    
    Headers:
    - X-RateLimit-Limit: Maximum requests allowed
    - X-RateLimit-Remaining: Requests remaining in window
    - X-RateLimit-Reset: Time when limit resets
    """
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)
        
        # Get rate limit info from request state if available
        rate_limit_info = getattr(request.state, "rate_limit_info", None)
        
        if rate_limit_info:
            response.headers["X-RateLimit-Limit"] = str(rate_limit_info.get("limit", 100))
            response.headers["X-RateLimit-Remaining"] = str(rate_limit_info.get("remaining", 100))
            response.headers["X-RateLimit-Reset"] = str(rate_limit_info.get("reset", 0))
        
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Middleware to add security headers to all responses.
    """
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)
        
        # Security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        
        # Only add HSTS in production
        # response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        
        return response


def setup_middleware(app):
    """
    Setup all middleware in correct order.
    
    Order matters - middleware is executed in reverse order of addition.
    """
    # Add in reverse order of desired execution
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RateLimitHeaderMiddleware)
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(RequestIDMiddleware)
