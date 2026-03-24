"""HumanReviewRepository — manages HumanReviewEvent records."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.orm_models import HumanReviewAction, HumanReviewEvent


class HumanReviewRepository:
    """Write and query HumanReviewEvent records."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        blog_session_id: int,
        blog_version_id: int,
        reviewer_user_id: str,
        action: HumanReviewAction,
        feedback_text: Optional[str] = None,
        review_context: Optional[dict] = None,
    ) -> HumanReviewEvent:
        event = HumanReviewEvent(
            blog_session_id=blog_session_id,
            blog_version_id=blog_version_id,
            reviewer_user_id=reviewer_user_id,
            action=action,
            feedback_text=feedback_text,
            review_context=review_context,
        )
        self._session.add(event)
        await self._session.flush()
        return event

    async def get_for_session(
        self, blog_session_id: int
    ) -> list[HumanReviewEvent]:
        result = await self._session.execute(
            select(HumanReviewEvent)
            .where(HumanReviewEvent.blog_session_id == blog_session_id)
            .order_by(HumanReviewEvent.created_at)
        )
        return list(result.scalars().all())

    async def get_latest_for_session(
        self, blog_session_id: int
    ) -> Optional[HumanReviewEvent]:
        result = await self._session.execute(
            select(HumanReviewEvent)
            .where(HumanReviewEvent.blog_session_id == blog_session_id)
            .order_by(HumanReviewEvent.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()
