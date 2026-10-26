"""Atomic per-user daily blog-generation quota backed by PostgreSQL."""

from datetime import date, datetime, timezone

from sqlalchemy import case, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.orm_models import UserBlogQuota


class BlogQuotaRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def consume_daily_slot(self, user_id: int, daily_limit: int, usage_date: date) -> bool:
        """Consume a generation slot atomically; return False once the cap is reached.

        A row lock taken by the upsert serializes concurrent requests for this user.
        The caller's transaction keeps the increment atomic with session creation and
        the workflow outbox insert; a failed generation request rolls it back.
        """
        now = datetime.now(timezone.utc)
        statement = insert(UserBlogQuota).values(
            user_id=user_id,
            blogs_used=1,
            blogs_limit=daily_limit,
            usage_date=usage_date,
            created_at=now,
            updated_at=now,
        )
        statement = statement.on_conflict_do_update(
            index_elements=[UserBlogQuota.user_id],
            set_={
                "blogs_used": case(
                    (UserBlogQuota.usage_date == usage_date, UserBlogQuota.blogs_used + 1),
                    else_=1,
                ),
                "blogs_limit": daily_limit,
                "usage_date": usage_date,
                "updated_at": now,
            },
            where=or_(
                UserBlogQuota.usage_date != usage_date,
                UserBlogQuota.blogs_used < daily_limit,
            ),
        ).returning(UserBlogQuota.blogs_used)
        result = await self._session.execute(statement)
        return result.scalar_one_or_none() is not None

    async def get_remaining(self, user_id: int, daily_limit: int, usage_date: date) -> int:
        """Read remaining slots without requiring a row to exist for every user."""
        result = await self._session.execute(
            select(UserBlogQuota.blogs_used, UserBlogQuota.usage_date).where(
                UserBlogQuota.user_id == user_id
            )
        )
        quota = result.one_or_none()
        if quota is None or quota.usage_date != usage_date:
            return daily_limit
        return max(0, daily_limit - quota.blogs_used)
