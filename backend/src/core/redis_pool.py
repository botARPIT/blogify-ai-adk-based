"""Centralised Redis connection pool.

All Redis consumers (TaskQueue, IdempotencyStore, RedisSessionStore,
RuntimeManager) share a single ConnectionPool instead of creating
private clients.  This caps TCP connections and simplifies shutdown.
"""

from __future__ import annotations

import redis.asyncio as redis

from src.config.database_config import db_settings
from src.config.logging_config import get_logger

logger = get_logger(__name__)

# ── Singleton pool ──────────────────────────────────────────────────
_pool: redis.ConnectionPool | None = None


def _ensure_pool() -> redis.ConnectionPool:
    """Create the shared pool on first access (lazy init)."""
    global _pool
    if _pool is None:
        _pool = redis.ConnectionPool.from_url(
            db_settings.redis_url,
            decode_responses=True,
            max_connections=20,
            socket_connect_timeout=5,
            socket_timeout=5,
        )
        logger.info("redis_pool_created", max_connections=20)
    return _pool


def get_redis_client() -> redis.Redis:
    """Return a Redis client backed by the shared pool.

    Callers should **not** call ``client.close()`` — the pool manages
    the underlying connections.  Call :func:`close_pool` once at
    process shutdown.
    """
    pool = _ensure_pool()
    return redis.Redis(connection_pool=pool)


async def close_pool() -> None:
    """Drain and close the shared connection pool.

    Safe to call multiple times.
    """
    global _pool
    if _pool is not None:
        await _pool.disconnect()
        _pool = None
        logger.info("redis_pool_closed")
