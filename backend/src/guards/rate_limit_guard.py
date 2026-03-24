"""Enhanced rate limiter with global and per-user limits."""

from src.config import budget_settings, settings
from src.config.logging_config import get_logger
from src.core.redis_pool import get_redis_client

logger = get_logger(__name__)


class EnhancedRateLimiter:
    """Redis-based rate limiter with global and per-user limits."""

    def __init__(self) -> None:
        # Per-user limits
        self.requests_per_minute = settings.rate_limit_requests_per_minute
        self.blogs_per_day = budget_settings.per_user_blogs_per_day
        
        # Global limits
        self.global_requests_per_minute = 100  # Global API limit
        self.global_blogs_per_day = 1000  # Global daily blog limit

    async def connect(self) -> None:
        """Warm the shared Redis pool."""
        get_redis_client()

    async def close(self) -> None:
        """No-op. Pool cleanup is centralised in redis_pool."""
        return None

    async def check_global_request_limit(self) -> tuple[bool, str]:
        """Check global request rate limit."""
        client = get_redis_client()

        key = "rate_limit:global:requests"
        current = await client.get(key)

        if current and int(current) >= self.global_requests_per_minute:
            logger.error("global_request_limit_exceeded", current=current)
            return False, f"Global rate limit exceeded. Try again later."

        # Increment counter
        pipe = client.pipeline()
        pipe.incr(key)
        pipe.expire(key, 60)  # 1 minute TTL
        await pipe.execute()

        return True, ""

    async def check_global_blog_limit(self) -> tuple[bool, str]:
        """Check global daily blog generation limit."""
        client = get_redis_client()

        key = "rate_limit:global:blogs"
        current = await client.get(key)

        if current and int(current) >= self.global_blogs_per_day:
            logger.error("global_blog_limit_exceeded", current=current)
            return False, f"Global daily blog limit reached. Try again tomorrow."

        return True, ""

    async def check_user_request_limit(self, user_id: str) -> tuple[bool, str]:
        """Check per-user request rate limit."""
        client = get_redis_client()

        key = f"rate_limit:user:requests:{user_id}"
        current = await client.get(key)

        if current and int(current) >= self.requests_per_minute:
            logger.warning("user_request_limit_exceeded", user_id=user_id, current=current)
            return False, f"Too many requests. Limit: {self.requests_per_minute}/minute"

        # Increment counter
        pipe = client.pipeline()
        pipe.incr(key)
        pipe.expire(key, 60)  # 1 minute TTL
        await pipe.execute()

        return True, ""

    async def check_user_blog_limit(self, user_id: str) -> tuple[bool, str]:
        """Check per-user daily blog generation limit."""
        client = get_redis_client()

        key = f"rate_limit:user:blogs:{user_id}"
        current = await client.get(key)

        if current and int(current) >= self.blogs_per_day:
            logger.warning("user_blog_limit_exceeded", user_id=user_id, current=current)
            return False, f"Daily blog limit reached. Limit: {self.blogs_per_day}/day"

        return True, ""

    async def increment_global_blog_count(self) -> None:
        """Increment global daily blog count."""
        client = get_redis_client()

        key = "rate_limit:global:blogs"
        pipe = client.pipeline()
        pipe.incr(key)
        pipe.expire(key, 86400)  # 24 hours TTL
        await pipe.execute()

    async def increment_user_blog_count(self, user_id: str) -> None:
        """Increment user's daily blog count."""
        client = get_redis_client()

        key = f"rate_limit:user:blogs:{user_id}"
        pipe = client.pipeline()
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
