"""JWT Authentication middleware.

Validates JWT tokens from external authentication service.
Extracts user identity and attaches to request state.
"""

import os
from typing import Callable

from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from src.config.logging_config import get_logger

logger = get_logger(__name__)

# Try to import jose for JWT handling
try:
    from jose import jwt, JWTError, ExpiredSignatureError
    JWT_AVAILABLE = True
except ImportError:
    JWT_AVAILABLE = False
    logger.warning("python-jose not installed - JWT validation disabled")


class AuthMiddleware(BaseHTTPMiddleware):
    """
    JWT authentication middleware.
    
    Validates Bearer tokens from Authorization header.
    Attaches user identity to request.state.
    
    Configuration via environment:
    - JWT_SECRET_KEY: Secret for HS256, or public key for RS256
    - JWT_ALGORITHM: Algorithm (default: HS256)
    - JWT_AUDIENCE: Expected audience claim
    - JWT_ISSUER: Expected issuer claim
    - AUTH_REQUIRED: Whether auth is required (default: true in prod)
    """
    
    # Routes that don't require authentication
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
    
    # Routes with prefix that are public
    PUBLIC_PREFIXES = {
        "/health",
    }
    
    def __init__(self, app, required: bool = True):
        super().__init__(app)
        self.required = required
        self.secret_key = os.getenv("JWT_SECRET_KEY", "")
        self.algorithm = os.getenv("JWT_ALGORITHM", "HS256")
        self.audience = os.getenv("JWT_AUDIENCE", "blogify-api")
        self.issuer = os.getenv("JWT_ISSUER", "")
    
    async def dispatch(self, request: Request, call_next: Callable):
        """Process request with JWT validation."""
        
        # Skip public routes
        if self._is_public_route(request.url.path):
            return await call_next(request)
        
        # Skip if JWT not available (dev mode)
        if not JWT_AVAILABLE:
            request.state.user_id = "dev-user"
            request.state.user_email = "dev@example.com"
            return await call_next(request)
        
        # Skip if auth not required (dev/test)
        if not self.required:
            # Use user_id from request body if available
            return await call_next(request)
        
        # Extract token
        auth_header = request.headers.get("Authorization")
        
        if not auth_header:
            return self._unauthorized("Missing Authorization header")
        
        if not auth_header.startswith("Bearer "):
            return self._unauthorized("Invalid Authorization header format")
        
        token = auth_header.split(" ", 1)[1]
        
        if not token:
            return self._unauthorized("Empty token")
        
        # Validate token
        try:
            payload = self._validate_token(token)
            
            # Attach user info to request state
            request.state.user_id = payload.get("sub")
            request.state.user_email = payload.get("email")
            request.state.token_claims = payload
            
            logger.debug(
                "auth_success",
                user_id=request.state.user_id,
                path=request.url.path,
            )
            
        except ExpiredSignatureError:
            return self._unauthorized("Token expired")
        except JWTError as e:
            logger.warning("jwt_validation_failed", error=str(e))
            return self._unauthorized(f"Invalid token: {str(e)}")
        except Exception as e:
            logger.error("auth_error", error=str(e))
            return self._unauthorized("Authentication failed")
        
        return await call_next(request)
    
    def _is_public_route(self, path: str) -> bool:
        """Check if route is public."""
        if path in self.PUBLIC_ROUTES:
            return True
        
        for prefix in self.PUBLIC_PREFIXES:
            if path.startswith(prefix):
                return True
        
        return False
    
    def _validate_token(self, token: str) -> dict:
        """
        Validate JWT token and return payload.
        
        Raises:
            JWTError: If token is invalid
        """
        options = {
            "verify_signature": True,
            "verify_exp": True,
            "verify_iat": True,
            "require_exp": True,
        }
        
        # Add audience/issuer verification if configured
        if self.audience:
            options["verify_aud"] = True
        if self.issuer:
            options["verify_iss"] = True
        
        payload = jwt.decode(
            token,
            self.secret_key,
            algorithms=[self.algorithm],
            audience=self.audience if self.audience else None,
            issuer=self.issuer if self.issuer else None,
            options=options,
        )
        
        return payload
    
    def _unauthorized(self, message: str) -> JSONResponse:
        """Return 401 Unauthorized response."""
        return JSONResponse(
            status_code=401,
            content={
                "error": "Unauthorized",
                "message": message,
            },
            headers={"WWW-Authenticate": "Bearer"},
        )


class OptionalAuthMiddleware(AuthMiddleware):
    """
    Optional authentication middleware.
    
    Sets user info if token present, but doesn't require it.
    Useful for endpoints that work both authenticated and anonymously.
    """
    
    def __init__(self, app):
        super().__init__(app, required=False)
    
    async def dispatch(self, request: Request, call_next: Callable):
        """Process request with optional JWT validation."""
        
        # Skip public routes
        if self._is_public_route(request.url.path):
            return await call_next(request)
        
        # Extract token if present
        auth_header = request.headers.get("Authorization")
        
        if auth_header and auth_header.startswith("Bearer ") and JWT_AVAILABLE:
            token = auth_header.split(" ", 1)[1]
            
            try:
                payload = self._validate_token(token)
                request.state.user_id = payload.get("sub")
                request.state.user_email = payload.get("email")
                request.state.token_claims = payload
                request.state.authenticated = True
            except Exception:
                # Token invalid but optional - continue without auth
                request.state.user_id = None
                request.state.authenticated = False
        else:
            request.state.user_id = None
            request.state.authenticated = False
        
        return await call_next(request)


def get_current_user(request: Request) -> str | None:
    """
    Get current user ID from request.
    
    Usage in route:
        @router.post("/protected")
        async def protected_route(request: Request):
            user_id = get_current_user(request)
            if not user_id:
                raise HTTPException(401, "Not authenticated")
    """
    return getattr(request.state, "user_id", None)


def require_auth(request: Request) -> str:
    """
    Require authentication and return user ID.
    
    Raises HTTPException if not authenticated.
    
    Usage in route:
        @router.post("/protected")
        async def protected_route(request: Request):
            user_id = require_auth(request)
            # user_id is guaranteed to be set
    """
    user_id = getattr(request.state, "user_id", None)
    
    if not user_id:
        raise HTTPException(
            status_code=401,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    return user_id
