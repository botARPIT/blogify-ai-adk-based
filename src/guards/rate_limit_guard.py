"""Enhanced rate limiter with global and per-user limits."""

import time
from typing import Optional

import redis.asyncio as redis

from src.config import budget_settings, settings
from src.config.database_config import db_settings
from src.config.logging_config import get_logger

logger = get_logger(__name__)


class EnhancedRateLimiter:
    """Redis-based rate limiter with global and per-user limits."""

    def __init__(self, redis_url: str | None = None) -> None:
        self.redis_url = redis_url or db_settings.redis_url
        self.redis_client: Optional[redis.Redis] = None
        
        # Per-user limits
        self.requests_per_minute = settings.rate_limit_requests_per_minute
        self.blogs_per_day = budget_settings.per_user_blogs_per_day
        
        # Global limits
        self.global_requests_per_minute = 100  # Global API limit
        self.global_blogs_per_day = 1000  # Global daily blog limit

    async def connect(self) -> None:
        """Connect to Redis."""
        if not self.redis_client:
            self.redis_client = await redis.from_url(self.redis_url, decode_responses=True)

    async def close(self) -> None:
        """Close Redis connection."""
        if self.redis_client:
            await self.redis_client.close()

    async def check_global_request_limit(self) -> tuple[bool, str]:
        """Check global request rate limit."""
        if not self.redis_client:
            await self.connect()

        key = "rate_limit:global:requests"
        current = await self.redis_client.get(key)

        if current and int(current) >= self.global_requests_per_minute:
            logger.error("global_request_limit_exceeded", current=current)
            return False, f"Global rate limit exceeded. Try again later."

        # Increment counter
        pipe = self.redis_client.pipeline()
        pipe.incr(key)
        pipe.expire(key, 60)  # 1 minute TTL
        await pipe.execute()

        return True, ""

    async def check_global_blog_limit(self) -> tuple[bool, str]:
        """Check global daily blog generation limit."""
        if not self.redis_client:
            await self.connect()

        key = "rate_limit:global:blogs"
        current = await self.redis_client.get(key)

        if current and int(current) >= self.global_blogs_per_day:
            logger.error("global_blog_limit_exceeded", current=current)
            return False, f"Global daily blog limit reached. Try again tomorrow."

        return True, ""

    async def check_user_request_limit(self, user_id: str) -> tuple[bool, str]:
        """Check per-user request rate limit."""
        if not self.redis_client:
            await self.connect()

        key = f"rate_limit:user:requests:{user_id}"
        current = await self.redis_client.get(key)

        if current and int(current) >= self.requests_per_minute:
            logger.warning("user_request_limit_exceeded", user_id=user_id, current=current)
            return False, f"Too many requests. Limit: {self.requests_per_minute}/minute"

        # Increment counter
        pipe = self.redis_client.pipeline()
        pipe.incr(key)
        pipe.expire(key, 60)  # 1 minute TTL
        await pipe.execute()

        return True, ""

    async def check_user_blog_limit(self, user_id: str) -> tuple[bool, str]:
        """Check per-user daily blog generation limit."""
        if not self.redis_client:
            await self.connect()

        key = f"rate_limit:user:blogs:{user_id}"
        current = await self.redis_client.get(key)

        if current and int(current) >= self.blogs_per_day:
            logger.warning("user_blog_limit_exceeded", user_id=user_id, current=current)
            return False, f"Daily blog limit reached. Limit: {self.blogs_per_day}/day"

        return True, ""

    async def increment_global_blog_count(self) -> None:
        """Increment global daily blog count."""
        if not self.redis_client:
            await self.connect()

        key = "rate_limit:global:blogs"
        pipe = self.redis_client.pipeline()
        pipe.incr(key)
        pipe.expire(key, 86400)  # 24 hours TTL
        await pipe.execute()

    async def increment_user_blog_count(self, user_id: str) -> None:
        """Increment user's daily blog count."""
        if not self.redis_client:
            await self.connect()

        key = f"rate_limit:user:blogs:{user_id}"
        pipe = self.redis_client.pipeline()
        pipe.incr(key)
        pipe.expire(key, 86400)  # 24 hours TTL
        await pipe.execute()

    async def check_all_limits(self, user_id: str, is_blog_request: bool = False) -> tuple[bool, str]:
        """
        Check all applicable rate limits.
        
        Args:
            user_id: User identifier
            is_blog_request: Whether this is a blog generation request
        
        Returns:
            (allowed, error_message)
        """
        # Global request limit
        allowed, msg = await self.check_global_request_limit()
        if not allowed:
            return False, msg

        # User request limit
        allowed, msg = await self.check_user_request_limit(user_id)
        if not allowed:
            return False, msg

        # Blog-specific limits
        if is_blog_request:
            # Global blog limit
            allowed, msg = await self.check_global_blog_limit()
            if not allowed:
                return False, msg

            # User blog limit
            allowed, msg = await self.check_user_blog_limit(user_id)
            if not allowed:
                return False, msg

        return True, ""


# Global instance
rate_limit_guard = EnhancedRateLimiter()
