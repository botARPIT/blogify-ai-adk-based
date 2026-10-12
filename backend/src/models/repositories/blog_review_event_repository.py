"""Persistence helpers for human review history."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.orm_models import BlogReviewEvent


class BlogReviewEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        blog_session_id: int,
        blog_version_id: int | None,
        reviewer_user_id: int,
        action: str,
        feedback_text: str | None,
    ) -> BlogReviewEvent:
        event = BlogReviewEvent(
            blog_session_id=blog_session_id,
            blog_version_id=blog_version_id,
            reviewer_user_id=reviewer_user_id,
            action=action,
            feedback_text=feedback_text,
        )
        self._session.add(event)
        await self._session.flush()
        return event

    async def get_for_session(self, blog_session_id: int) -> list[BlogReviewEvent]:
        result = await self._session.execute(
            select(BlogReviewEvent)
            .where(BlogReviewEvent.blog_session_id == blog_session_id)
            .order_by(BlogReviewEvent.created_at, BlogReviewEvent.id)
        )
        return list(result.scalars().all())
