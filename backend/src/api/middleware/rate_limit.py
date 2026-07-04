"""Middleware that enforces per-user and global rate limits via Redis sliding window."""

from collections.abc import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from src.config.env_config import config
from src.monitoring.metrics import rate_limit_rejections_total
from src.services.rate_limiter import get_limiter, is_public_path


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if is_public_path(request.url.path):
            return await call_next(request)

        user_id = getattr(request.state, "user_id", None)
        identity = user_id or request.client.host

        limiter = await get_limiter()
        result = await limiter.check_service_global()
        if not result.allowed:
            rate_limit_rejections_total.labels(limit_type="service_global").inc()
            return Response(
                status_code=503,
                content='{"error":"Service at capacity","retry_after":' + str(result.reset_at_unix) + "}",
                media_type="application/json",
                headers={
                    "Retry-After": str(result.reset_at_unix),
                    "X-RateLimit-Limit": str(config.service_rate_limit_requests_per_minute),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(result.reset_at_unix),
                },
            )

        result = await limiter.check_request_rate(identity)
        if not result.allowed:
            rate_limit_rejections_total.labels(limit_type="per_user_request").inc()
            return Response(
                status_code=429,
                content='{"error":"Rate limit exceeded","retry_after":' + str(result.reset_at_unix) + "}",
                media_type="application/json",
                headers={
                    "Retry-After": str(result.reset_at_unix),
                    "X-RateLimit-Limit": str(config.rate_limit_requests_per_minute),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(result.reset_at_unix),
                },
            )

        response = await call_next(request)

        response.headers["X-RateLimit-Limit"] = str(config.rate_limit_requests_per_minute)
        response.headers["X-RateLimit-Remaining"] = str(result.remaining)
        response.headers["X-RateLimit-Reset"] = str(result.reset_at_unix)

        return response
