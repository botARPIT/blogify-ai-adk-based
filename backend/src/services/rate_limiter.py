"""Redis-backed sliding window rate limiter using Lua scripting."""

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from redis.asyncio import Redis
from redis.exceptions import NoScriptError

from src.config.env_config import config
from src.core.redis_pool import get_redis_client

SLIDING_WINDOW_LUA = """
local key    = KEYS[1]
local now    = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit  = tonumber(ARGV[3])
local member = ARGV[4]

local cutoff = now - window
redis.call("ZREMRANGEBYSCORE", key, "-inf", cutoff)
local count = tonumber(redis.call("ZCARD", key))

if count >= limit then
    local oldest = tonumber(redis.call("ZRANGE", key, 0, 0, "WITHSCORES")[2])
    return {0, 0, math.floor(oldest + window)}
end

redis.call("ZADD", key, now, member)
redis.call("EXPIRE", key, window)

return {1, limit - count - 1, math.floor(now + window)}
"""


@dataclass(slots=True)
class RateLimitResult:
    allowed: bool
    remaining: int
    reset_at_unix: int


PUBLIC_PATHS = frozenset({
    "/",
    "/metrics",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/api/health",
    "/api/v1/health",
    "/api/v1/auth/login",
    "/api/v1/auth/register",
})


def is_public_path(path: str) -> bool:
    return path in PUBLIC_PATHS or path.startswith((
        "/docs/", "/redoc/", "/openapi.json", "/api/health/", "/api/v1/health/",
    ))


class RedisRateLimiter:
    def __init__(self, redis: Redis, *, key_prefix: str = "ratelimit") -> None:
        self._redis = redis
        self._key_prefix = key_prefix
        self._sha: str | None = None

    async def _load_script(self) -> str:
        if self._sha is None:
            self._sha = await self._redis.script_load(SLIDING_WINDOW_LUA)
        return self._sha

    async def check(
        self,
        key: str,
        limit: int,
        window_sec: int,
    ) -> RateLimitResult:
        sha = await self._load_script()
        now = int(datetime.now(timezone.utc).timestamp())
        member = uuid.uuid4().hex
        try:
            result = await self._redis.evalsha(sha, 1, key, now, window_sec, limit, member)
        except NoScriptError:
            self._sha = None
            sha = await self._load_script()
            result = await self._redis.evalsha(sha, 1, key, now, window_sec, limit, member)
        allowed, remaining, reset_at = bool(result[0]), int(result[1]), int(result[2])
        return RateLimitResult(allowed=allowed, remaining=remaining, reset_at_unix=reset_at)

    async def check_request_rate(self, identity: str) -> RateLimitResult:
        return await self.check(
            key=f"{self._key_prefix}:req:{identity}",
            limit=config.rate_limit_requests_per_minute,
            window_sec=60,
        )

    async def check_service_global(self) -> RateLimitResult:
        return await self.check(
            key=f"{self._key_prefix}:service:global",
            limit=config.service_rate_limit_requests_per_minute,
            window_sec=60,
        )


_limiter: RedisRateLimiter | None = None


async def get_limiter() -> RedisRateLimiter:
    global _limiter
    if _limiter is None:
        _limiter = RedisRateLimiter(await get_redis_client())
    return _limiter
