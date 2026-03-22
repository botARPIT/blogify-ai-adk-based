"""BlogSessionRepository — manages BlogSession lifecycle."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.orm_models import BlogSession, BlogSessionStatus


class BlogSessionRepository:
    """Create, read, and update BlogSession records."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        tenant_id: int,
        end_user_id: int,
        service_client_id: int,
        topic: str,
        audience: Optional[str] = None,
        tone: Optional[str] = None,
        external_request_id: Optional[str] = None,
        external_blog_id: Optional[str] = None,
        budget_reserved_usd: float = 0.0,
        budget_reserved_tokens: int = 0,
    ) -> BlogSession:
        blog_session = BlogSession(
            tenant_id=tenant_id,
            end_user_id=end_user_id,
            service_client_id=service_client_id,
            topic=topic,
            audience=audience,
            tone=tone,
            external_request_id=external_request_id,
            external_blog_id=external_blog_id,
            status=BlogSessionStatus.QUEUED.value,
            budget_reserved_usd=budget_reserved_usd,
            budget_reserved_tokens=budget_reserved_tokens,
        )
        self._session.add(blog_session)
        await self._session.flush()
        return blog_session

    async def get_by_id(self, session_id: int) -> Optional[BlogSession]:
        result = await self._session.execute(
            select(BlogSession).where(BlogSession.id == session_id)
        )
        return result.scalar_one_or_none()

    async def get_by_external_request_id(
        self, external_request_id: str
    ) -> Optional[BlogSession]:
        result = await self._session.execute(
            select(BlogSession).where(
                BlogSession.external_request_id == external_request_id
            )
        )
        return result.scalar_one_or_none()

    async def update_status(
        self,
        session_id: int,
        status: BlogSessionStatus,
        current_stage: Optional[str] = None,
    ) -> None:
        blog_session = await self.get_by_id(session_id)
        if blog_session:
            blog_session.status = status.value
            if current_stage is not None:
                blog_session.current_stage = current_stage
            blog_session.updated_at = datetime.now(timezone.utc)
            if status == BlogSessionStatus.COMPLETED:
                blog_session.completed_at = datetime.now(timezone.utc)

    async def commit_spend(
        self,
        session_id: int,
        additional_usd: float,
        additional_tokens: int,
    ) -> None:
        blog_session = await self.get_by_id(session_id)
        if blog_session:
            blog_session.budget_spent_usd += additional_usd
            blog_session.budget_spent_tokens += additional_tokens
            blog_session.updated_at = datetime.now(timezone.utc)

    async def increment_iteration(self, session_id: int) -> int:
        """Increment revision iteration count and return new value."""
        blog_session = await self.get_by_id(session_id)
        if blog_session:
            blog_session.iteration_count += 1
            blog_session.updated_at = datetime.now(timezone.utc)
            return blog_session.iteration_count
        return 0
