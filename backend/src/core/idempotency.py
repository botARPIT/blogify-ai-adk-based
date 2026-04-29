"""Idempotency support for API requests.

Prevents duplicate blog generations on client retries.
Uses Redis to track idempotency keys.
"""

import enum
import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from src.config.logging_config import get_logger
from src.core.redis_pool import get_redis_client

logger = get_logger(__name__)


class IdempotencyState(enum.Enum):
    """Result state from an idempotency check."""

    NEW = "new"               # First time seeing this key — proceed
    CACHED = "cached"         # Already completed — return cached response
    IN_PROGRESS = "in_progress"  # Another request is processing this
    MISMATCH = "mismatch"     # Key reused with a different payload


@dataclass
class IdempotencyResult:
    """Holds the outcome of an idempotency check."""

    state: IdempotencyState
    response: dict | None = None
    status_code: int | None = None


class IdempotencyStore:
    """
    Redis-backed idempotency key store.

    Features:
    - Prevents duplicate request processing
    - Stores and returns cached responses
    - Automatic TTL-based cleanup
    - Thread-safe atomic operations
    """

    KEY_PREFIX = "idempotency:"
    DEFAULT_TTL = 86400  # 24 hours

    def __init__(self):
        pass

    async def _get_client(self):
        """Return a Redis client from the shared pool."""
        return get_redis_client()

    def _generate_key(
        self,
        user_scope: str,
        endpoint: str,
        idempotency_key: str,
    ) -> str:
        """Generate Redis key for idempotency."""
        return f"{self.KEY_PREFIX}{user_scope}:{endpoint}:{idempotency_key}"

    def _hash_body(self, request_body: dict | None) -> str:
        """Deterministic hash of the request body for mismatch detection."""
        if not request_body:
            return ""
        return hashlib.sha256(
            json.dumps(request_body, sort_keys=True).encode()
        ).hexdigest()

    async def check_and_set(
        self,
        *,
        user_scope: str,
        endpoint: str,
        idempotency_key: str,
        request_body: dict | None = None,
        ttl: int | None = None,
    ) -> IdempotencyResult:
        """
        Check if request is duplicate and set lock if not.

        Returns an IdempotencyResult with:
        - NEW: first time — caller should proceed
        - CACHED: completed before — return the cached response
        - IN_PROGRESS: another handler is working on it
        - MISMATCH: key reused with different body
        """
        client = await self._get_client()
        ttl = ttl or self.DEFAULT_TTL
        key = self._generate_key(user_scope, endpoint, idempotency_key)
        body_hash = self._hash_body(request_body)

        existing_raw = await client.get(key)

        if existing_raw:
            data = json.loads(existing_raw)

            # Check payload mismatch
            if data.get("body_hash") and body_hash and data["body_hash"] != body_hash:
                logger.warning("idempotency_mismatch", key=key)
                return IdempotencyResult(state=IdempotencyState.MISMATCH)

            if data.get("status") == "completed":
                logger.info("idempotency_cache_hit", key=key)
                return IdempotencyResult(
                    state=IdempotencyState.CACHED,
                    response=data.get("response"),
                    status_code=data.get("status_code"),
                )

            if data.get("status") == "processing":
                logger.info("idempotency_in_progress", key=key)
                return IdempotencyResult(state=IdempotencyState.IN_PROGRESS)

        # Set processing lock
        lock_data = {
            "status": "processing",
            "started_at": datetime.utcnow().isoformat(),
            "user_scope": user_scope,
            "endpoint": endpoint,
            "body_hash": body_hash,
        }

        # Use SET NX for atomic check-and-set
        set_result = await client.set(
            key,
            json.dumps(lock_data),
            ex=ttl,
            nx=True,
        )

        if not set_result:
            # Another request got there first — re-read
            existing_raw = await client.get(key)
            if existing_raw:
                data = json.loads(existing_raw)
                if data.get("status") == "completed":
                    return IdempotencyResult(
                        state=IdempotencyState.CACHED,
                        response=data.get("response"),
                        status_code=data.get("status_code"),
                    )
                return IdempotencyResult(state=IdempotencyState.IN_PROGRESS)
            return IdempotencyResult(state=IdempotencyState.IN_PROGRESS)

        logger.info("idempotency_lock_acquired", key=key)
        return IdempotencyResult(state=IdempotencyState.NEW)

    async def set_response(
        self,
        *,
        user_scope: str,
        endpoint: str,
        idempotency_key: str,
        request_body: dict | None = None,
        status_code: int = 200,
        response_body: dict | None = None,
        ttl: int | None = None,
    ) -> None:
        """Store a completed response for this idempotency key."""
        client = await self._get_client()
        ttl = ttl or self.DEFAULT_TTL
        key = self._generate_key(user_scope, endpoint, idempotency_key)
        body_hash = self._hash_body(request_body)

        data = {
            "status": "completed",
            "response": response_body,
            "status_code": status_code,
            "completed_at": datetime.utcnow().isoformat(),
            "user_scope": user_scope,
            "endpoint": endpoint,
            "body_hash": body_hash,
        }

        await client.set(key, json.dumps(data), ex=ttl)
        logger.info("idempotency_response_cached", key=key, status_code=status_code)

    async def clear(
        self,
        *,
        user_scope: str,
        endpoint: str,
        idempotency_key: str,
    ) -> None:
        """Clear an idempotency key (on failure/non-cacheable error)."""
        client = await self._get_client()
        key = self._generate_key(user_scope, endpoint, idempotency_key)
        await client.delete(key)
        logger.info("idempotency_key_cleared", key=key)

    async def close(self):
        """No-op. Pool cleanup is centralised in redis_pool."""
        pass


# Global instance
idempotency_store = IdempotencyStore()


# FastAPI dependency for idempotency
from fastapi import Header, Request


async def get_idempotency_key(
    request: Request,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
) -> str | None:
    """
    FastAPI dependency to extract idempotency key.

    Usage:
        @router.post("/blogs/generate")
        async def generate(
            request: BlogRequest,
            idem_key: str | None = Depends(get_idempotency_key)
        ):
            ...
    """
    return idempotency_key
