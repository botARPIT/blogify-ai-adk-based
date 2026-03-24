"""Authentication helpers for cookie-based local auth and optional bearer auth."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware

from src.config.logging_config import get_logger
from src.services.local_auth_service import AUTH_COOKIE_NAME, LocalAuthService

logger = get_logger(__name__)


@dataclass(slots=True)
class AuthenticatedUser:
    user_id: str
    email: str | None = None
    display_name: str | None = None
    token_claims: dict | None = None


class AuthMiddleware(BaseHTTPMiddleware):
    """Attach authenticated user context when a cookie or bearer token is present."""

    PUBLIC_ROUTES = {
        "/",
        "/docs",
        "/redoc",
        "/openapi.json",
        "/health",
        "/api/health",
        "/api/health/live",
        "/api/health/ready",
        "/api/health/detailed",
        "/metrics",
    }
    PUBLIC_PREFIXES = {
        "/health",
    }

    def __init__(self, app, required: bool = False):
        super().__init__(app)
        self.required = required
        self.local_auth = LocalAuthService()

    async def dispatch(self, request: Request, call_next: Callable):
        request.state.user_id = None
        request.state.user_email = None
        request.state.user_display_name = None
        request.state.token_claims = None
        request.state.authenticated = False

        if self._is_public_route(request.url.path):
            return await call_next(request)

        token = self._extract_token(request)
        if token:
            try:
                payload = self.local_auth.decode_token(token)
                request.state.user_id = payload.get("sub")
                request.state.user_email = payload.get("email")
                request.state.user_display_name = payload.get("display_name")
                request.state.token_claims = payload
                request.state.authenticated = True
            except Exception as exc:  # noqa: BLE001
                logger.warning("auth_token_invalid", path=request.url.path, error=str(exc))

        return await call_next(request)

    def _extract_token(self, request: Request) -> str | None:
        cookie_token = request.cookies.get(AUTH_COOKIE_NAME)
        if cookie_token:
            return cookie_token
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            return auth_header.split(" ", 1)[1]
        return None

    def _is_public_route(self, path: str) -> bool:
        if path in self.PUBLIC_ROUTES:
            return True
        return any(path.startswith(prefix) for prefix in self.PUBLIC_PREFIXES)


class OptionalAuthMiddleware(AuthMiddleware):
    pass


def get_current_user(request: Request) -> AuthenticatedUser | None:
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        return None
    return AuthenticatedUser(
        user_id=str(user_id),
        email=getattr(request.state, "user_email", None),
        display_name=getattr(request.state, "user_display_name", None),
        token_claims=getattr(request.state, "token_claims", None),
    )


def require_authenticated_user(request: Request) -> AuthenticatedUser:
    user = get_current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


def require_auth(request: Request) -> str:
    return require_authenticated_user(request).user_id


def ensure_csrf_header(request: Request) -> None:
    if request.method.upper() in {"GET", "HEAD", "OPTIONS"}:
        return
    if request.headers.get("X-Requested-With") != "XMLHttpRequest":
        raise HTTPException(status_code=403, detail="Missing CSRF header")
