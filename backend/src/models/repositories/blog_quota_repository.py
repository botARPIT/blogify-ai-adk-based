"""BlogQuotaRepository — manages per-user blog generation quotas."""

from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.orm_models import UserBlogQuota

_BLOG_LIMIT = 10


class BlogQuotaRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_or_create(self, user_id: int) -> UserBlogQuota:
        """Return the quota row for this user, creating it if it doesn't exist."""
        result = await self._session.execute(
            select(UserBlogQuota).where(UserBlogQuota.user_id == user_id)
        )
        quota = result.scalar_one_or_none()
        if quota is None:
            quota = UserBlogQuota(
                user_id=user_id,
                blogs_used=0,
                blogs_limit=_BLOG_LIMIT,
            )
            self._session.add(quota)
            await self._session.flush()
        return quota

    async def get_remaining(self, user_id: int) -> int:
        """Return the number of blogs the user can still generate."""
        quota = await self.get_or_create(user_id)
        return max(0, quota.blogs_limit - quota.blogs_used)

    async def increment_used(self, user_id: int) -> int:
        """Atomically increment blogs_used by 1. Returns the new blogs_used count."""
        quota = await self.get_or_create(user_id)
        await self._session.execute(
            update(UserBlogQuota)
            .where(UserBlogQuota.user_id == user_id)
            .values(
                blogs_used=UserBlogQuota.blogs_used + 1,
                updated_at=datetime.now(timezone.utc),
            )
        )
        await self._session.flush()
        # Refresh to get the authoritative value from DB
        await self._session.refresh(quota)
        return quota.blogs_used
