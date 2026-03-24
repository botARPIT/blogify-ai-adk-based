"""Idempotency support for API requests.

Prevents duplicate blog generations on client retries.
Uses Redis to track idempotency keys.
"""

import hashlib
import json
from datetime import datetime, timedelta
from typing import Any

from src.config.logging_config import get_logger
from src.core.redis_pool import get_redis_client

logger = get_logger(__name__)


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
        idempotency_key: str | None,
        user_id: str,
        endpoint: str,
        body_hash: str | None = None,
    ) -> str:
        """
        Generate Redis key for idempotency.
        
        If no idempotency_key provided, generates one from request content.
        """
        if idempotency_key:
            return f"{self.KEY_PREFIX}{user_id}:{idempotency_key}"
        
        # Generate from request content
        content = f"{user_id}:{endpoint}:{body_hash or ''}"
        generated_key = hashlib.sha256(content.encode()).hexdigest()[:32]
        return f"{self.KEY_PREFIX}{user_id}:{generated_key}"
    
    async def check_and_set(
        self,
        user_id: str,
        endpoint: str,
        idempotency_key: str | None = None,
        request_body: dict | None = None,
        ttl: int | None = None,
    ) -> tuple[bool, dict | None]:
        """
        Check if request is duplicate and set lock if not.
        
        Args:
            user_id: User identifier
            endpoint: API endpoint
            idempotency_key: Optional client-provided key
            request_body: Request body for hashing
            ttl: Time-to-live in seconds
            
        Returns:
            (is_new, cached_response)
            - (True, None) if new request
            - (False, response) if duplicate with cached response
            - (False, None) if duplicate in progress
        """
        client = await self._get_client()
        ttl = ttl or self.DEFAULT_TTL
        
        # Generate key
        body_hash = None
        if request_body:
            body_hash = hashlib.sha256(json.dumps(request_body, sort_keys=True).encode()).hexdigest()
        
        key = self._generate_key(idempotency_key, user_id, endpoint, body_hash)
        
        # Check existing
        existing = await client.get(key)
        
        if existing:
            data = json.loads(existing)
            
            if data.get("status") == "processing":
                logger.info("idempotency_in_progress", key=key)
                return False, None
            
            if data.get("status") == "completed":
                logger.info("idempotency_cache_hit", key=key)
                return False, data.get("response")
        
        # Set processing lock
        lock_data = {
            "status": "processing",
            "started_at": datetime.utcnow().isoformat(),
            "user_id": user_id,
            "endpoint": endpoint,
        }
        
        # Use SET NX for atomic check-and-set
        set_result = await client.set(
            key,
            json.dumps(lock_data),
            ex=ttl,
            nx=True,  # Only set if not exists
        )
        
        if not set_result:
            # Another request got there first
            existing = await client.get(key)
            if existing:
                data = json.loads(existing)
                return False, data.get("response")
            return False, None
        
        logger.info("idempotency_lock_acquired", key=key)
        return True, None
    
    async def set_response(
        self,
        user_id: str,
        endpoint: str,
        response: dict,
        idempotency_key: str | None = None,
        request_body: dict | None = None,
        ttl: int | None = None,
    ) -> None:
        """
        Store successful response for idempotency key.
        
        Args:
            user_id: User identifier
            endpoint: API endpoint
            response: Response to cache
            idempotency_key: Client-provided key
            request_body: Request body for hashing
            ttl: Time-to-live
        """
        client = await self._get_client()
        ttl = ttl or self.DEFAULT_TTL
        
        body_hash = None
        if request_body:
            body_hash = hashlib.sha256(json.dumps(request_body, sort_keys=True).encode()).hexdigest()
        
        key = self._generate_key(idempotency_key, user_id, endpoint, body_hash)
        
        data = {
            "status": "completed",
            "response": response,
            "completed_at": datetime.utcnow().isoformat(),
            "user_id": user_id,
            "endpoint": endpoint,
        }
        
        await client.set(key, json.dumps(data), ex=ttl)
        logger.info("idempotency_response_cached", key=key)
    
    async def clear(
        self,
        user_id: str,
        endpoint: str,
        idempotency_key: str | None = None,
        request_body: dict | None = None,
    ) -> None:
        """Clear an idempotency key (on failure)."""
        client = await self._get_client()
        
        body_hash = None
        if request_body:
            body_hash = hashlib.sha256(json.dumps(request_body, sort_keys=True).encode()).hexdigest()
        
        key = self._generate_key(idempotency_key, user_id, endpoint, body_hash)
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
