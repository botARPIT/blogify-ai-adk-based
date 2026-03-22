"""Request middleware for tracking, timing, logging, and rate limiting.

Production-grade middleware stack including:
- Request ID tracking (correlation)
- Request/response logging with timing
- Rate limit headers
- Security headers
- Scalability optimizations
"""

import asyncio
import time
import uuid
from datetime import datetime, timedelta
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from src.config.logging_config import get_logger
from src.monitoring.metrics import http_requests_total, http_request_duration_seconds

logger = get_logger(__name__)


class RequestIDMiddleware(BaseHTTPMiddleware):
    """
    Middleware to add unique request ID to each request.
    
    Features:
    - Generates UUID if X-Request-ID not provided
    - Stores in request.state for handler access
    - Returns in X-Request-ID response header
    - Enables distributed tracing
    """
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Get or generate request ID
        request_id = request.headers.get("X-Request-ID")
        if not request_id:
            request_id = str(uuid.uuid4())
        
        # Store in request state for access in handlers
        request.state.request_id = request_id
        request.state.start_time = time.time()
        
        # Process request
        response = await call_next(request)
        
        # Add request ID to response headers
        response.headers["X-Request-ID"] = request_id
        
        return response


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware to log all requests with timing and metrics.
    
    Logs:
    - Request method, path, status code
    - Response time (ms)
    - Request ID for correlation
    - Client IP (if available)
    """
    
    # Skip logging for these paths (health checks, metrics)
    SKIP_PATHS = {"/api/health", "/health", "/metrics", "/health/live", "/health/ready"}
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start_time = time.time()
        
        # Process request
        response = await call_next(request)
        
        # Calculate duration
        duration = time.time() - start_time
        duration_ms = duration * 1000
        
        # Get request ID
        request_id = getattr(request.state, "request_id", "unknown")
        
        # Skip logging for health checks
        if request.url.path not in self.SKIP_PATHS:
            # Get client IP
            client_ip = request.client.host if request.client else "unknown"
            forwarded_for = request.headers.get("X-Forwarded-For", "")
            if forwarded_for:
                client_ip = forwarded_for.split(",")[0].strip()
            
            # Log request
            logger.info(
                "http_request",
                request_id=request_id,
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                duration_ms=round(duration_ms, 2),
                client_ip=client_ip,
            )
        
        # Record Prometheus metrics
        try:
            # Normalize path for metrics (remove IDs)
            normalized_path = self._normalize_path(request.url.path)
            
            http_requests_total.labels(
                method=request.method,
                endpoint=normalized_path,
                status_code=str(response.status_code)
            ).inc()
            
            http_request_duration_seconds.labels(
                method=request.method,
                endpoint=normalized_path
            ).observe(duration)
        except Exception:
            pass  # Don't fail request if metrics fail
        
        # Add timing header
        response.headers["X-Response-Time"] = f"{duration_ms:.2f}ms"
        
        return response
    
    def _normalize_path(self, path: str) -> str:
        """Normalize path by replacing IDs with placeholders."""
        import re
        # Replace UUIDs
        path = re.sub(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', '{id}', path, flags=re.I)
        # Replace numeric IDs
        path = re.sub(r'/\d+', '/{id}', path)
        return path


class RateLimitHeaderMiddleware(BaseHTTPMiddleware):
    """
    Middleware to add rate limit headers to responses.
    
    Headers:
    - X-RateLimit-Limit: Maximum requests allowed in window
    - X-RateLimit-Remaining: Requests remaining in current window
    - X-RateLimit-Reset: Unix timestamp when window resets
    - Retry-After: Seconds until retry (only on 429)
    """
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)
        
        # Get rate limit info from request state if available
        rate_limit_info = getattr(request.state, "rate_limit_info", None)
        
        if rate_limit_info:
            response.headers["X-RateLimit-Limit"] = str(rate_limit_info.get("limit", 100))
            response.headers["X-RateLimit-Remaining"] = str(rate_limit_info.get("remaining", 100))
            response.headers["X-RateLimit-Reset"] = str(rate_limit_info.get("reset", 0))
            
            # Add Retry-After for rate limited responses
            if response.status_code == 429:
                retry_after = rate_limit_info.get("retry_after", 60)
                response.headers["Retry-After"] = str(retry_after)
        else:
            # Default rate limit headers
            from src.config.env_config import config
            reset_time = int((datetime.utcnow() + timedelta(minutes=1)).timestamp())
            response.headers["X-RateLimit-Limit"] = str(config.rate_limit_requests_per_minute)
            response.headers["X-RateLimit-Reset"] = str(reset_time)
        
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Middleware to add security headers to all responses.
    
    Headers:
    - X-Content-Type-Options: nosniff
    - X-Frame-Options: DENY
    - X-XSS-Protection: 1; mode=block
    - Referrer-Policy: strict-origin-when-cross-origin
    - Content-Security-Policy (basic)
    """
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)
        
        # Security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        
        # Basic CSP for API (allows JSON responses)
        response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
        
        # Cache control for API responses
        if request.method == "GET" and "/health" not in request.url.path:
            response.headers["Cache-Control"] = "no-store, max-age=0"
        
        return response


class ConcurrencyLimitMiddleware(BaseHTTPMiddleware):
    """
    Middleware to limit concurrent requests for scalability.
    
    Uses a semaphore to prevent overload during traffic spikes.
    Returns 503 if too many requests are in flight.
    """
    
    def __init__(self, app, max_concurrent: int = 100):
        super().__init__(app)
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.max_concurrent = max_concurrent
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Skip for health checks
        if request.url.path in {"/health", "/api/health", "/health/live"}:
            return await call_next(request)
        
        # Try to acquire semaphore without blocking
        acquired = self.semaphore.locked()
        
        if acquired and self.semaphore._value == 0:
            # At capacity - return 503
            return Response(
                content='{"error": "Service temporarily overloaded"}',
                status_code=503,
                media_type="application/json",
                headers={"Retry-After": "5"}
            )
        
        async with self.semaphore:
            return await call_next(request)


def setup_middleware(app):
    """
    Setup all middleware in correct order.
    
    Order matters - middleware is executed in reverse order of addition.
    First added = last executed on request, first on response.
    
    Execution order on REQUEST:
    1. RequestIDMiddleware (generates ID)
    2. AuthMiddleware (validates JWT) - NEW
    3. RequestLoggingMiddleware (logs request)
    4. RateLimitHeaderMiddleware (checks limits)
    5. SecurityHeadersMiddleware (adds headers)
    6. ConcurrencyLimitMiddleware (controls load)
    """
    import os
    from src.config.env_config import config
    from src.api.auth import AuthMiddleware
    
    # Determine if auth is required (default: false in dev, true in prod)
    auth_required = os.getenv("AUTH_REQUIRED", "false").lower() == "true"
    if config.environment == "prod":
        auth_required = True
    
    # Add in reverse order of desired execution
    app.add_middleware(ConcurrencyLimitMiddleware, max_concurrent=config.max_concurrent_requests)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RateLimitHeaderMiddleware)
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(AuthMiddleware, required=auth_required)
    app.add_middleware(RequestIDMiddleware)
