"""Persistence helpers for durable blog version snapshots."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.orm_models import BlogJobPhase, BlogSession, BlogSessionStatus, BlogVersion


class BlogVersionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_initial_version(
        self,
        *,
        blog_session: BlogSession,
        created_from: str,
        state_snapshot: dict[str, Any],
    ) -> BlogVersion:
        version = BlogVersion(
            blog_session_id=blog_session.id,
            version_number=1,
            status=blog_session.status,
            job_phase=BlogJobPhase.FRESH_GENERATION.value,
            title=blog_session.topic,
            adk_session_id=blog_session.adk_session_id,
            state_snapshot=state_snapshot,
            created_from=created_from,
        )
        self._session.add(version)
        await self._session.flush()
        blog_session.active_blog_version_id = version.id
        blog_session.job_phase = BlogJobPhase.FRESH_GENERATION.value
        blog_session.updated_at = datetime.now(timezone.utc)
        await self._session.flush()
        return version

    async def get_by_id(self, version_id: int) -> BlogVersion | None:
        result = await self._session.execute(select(BlogVersion).where(BlogVersion.id == version_id))
        return result.scalar_one_or_none()

    async def get_active_for_session(
        self,
        session_id: int,
        *,
        for_update: bool = False,
    ) -> BlogVersion | None:
        stmt = (
            select(BlogVersion)
            .join(BlogSession, BlogSession.active_blog_version_id == BlogVersion.id)
            .where(BlogSession.id == session_id)
        )
        if for_update:
            stmt = stmt.with_for_update()
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_latest_for_session(self, session_id: int) -> BlogVersion | None:
        result = await self._session.execute(
            select(BlogVersion)
            .where(BlogVersion.blog_session_id == session_id)
            .order_by(BlogVersion.version_number.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_next_version_number(self, session_id: int) -> int:
        result = await self._session.execute(
            select(func.coalesce(func.max(BlogVersion.version_number), 0)).where(
                BlogVersion.blog_session_id == session_id
            )
        )
        return int(result.scalar_one() or 0) + 1

    async def create_revision_from_active(
        self,
        *,
        blog_session: BlogSession,
        active_version: BlogVersion,
        feedback_text: str | None,
    ) -> BlogVersion:
        next_number = await self.get_next_version_number(blog_session.id)
        snapshot = dict(active_version.state_snapshot or {})
        if feedback_text is not None:
            snapshot["outline_feedback"] = feedback_text

        revision = BlogVersion(
            blog_session_id=blog_session.id,
            version_number=next_number,
            status=BlogSessionStatus.QUEUED.value,
            job_phase=BlogJobPhase.REVISION.value,
            title=active_version.title or blog_session.topic,
            outline_data=active_version.outline_data,
            approved_outline=active_version.approved_outline,
            research_data=active_version.research_data,
            draft_content=active_version.draft_content,
            final_content=active_version.final_content,
            editor_review=active_version.editor_review,
            feedback_text=feedback_text,
            adk_session_id=active_version.adk_session_id or blog_session.adk_session_id,
            invocation_id=active_version.invocation_id,
            confirmation_request_id=active_version.confirmation_request_id,
            state_snapshot=snapshot,
            created_from=BlogJobPhase.REVISION.value,
        )
        self._session.add(revision)
        await self._session.flush()

        blog_session.active_blog_version_id = revision.id
        blog_session.updated_at = datetime.now(timezone.utc)
        await self._session.flush()
        return revision

    async def update_version_state(
        self,
        version_id: int,
        *,
        status: str | None = None,
        job_phase: str | None = None,
        title: str | None = None,
        outline_data: dict | None = None,
        approved_outline: dict | None = None,
        research_data: dict | None = None,
        draft_content: str | None = None,
        final_content: str | None = None,
        editor_review: dict | None = None,
        feedback_text: str | None = None,
        user_action: str | None = None,
        adk_session_id: str | None = None,
        invocation_id: str | None = None,
        confirmation_request_id: str | None = None,
        state_snapshot: dict[str, Any] | None = None,
        completed: bool = False,
        failed: bool = False,
    ) -> BlogVersion | None:
        version = await self.get_by_id(version_id)
        if version is None:
            return None

        if status is not None:
            version.status = status
        if job_phase is not None:
            version.job_phase = job_phase
        if title is not None:
            version.title = title
        if outline_data is not None:
            version.outline_data = outline_data
        if approved_outline is not None:
            version.approved_outline = approved_outline
        if research_data is not None:
            version.research_data = research_data
        if draft_content is not None:
            version.draft_content = draft_content
        if final_content is not None:
            version.final_content = final_content
        if editor_review is not None:
            version.editor_review = editor_review
        if feedback_text is not None:
            version.feedback_text = feedback_text
        if user_action is not None:
            version.user_action = user_action
        if adk_session_id is not None:
            version.adk_session_id = adk_session_id
        if invocation_id is not None:
            version.invocation_id = invocation_id
        if confirmation_request_id is not None:
            version.confirmation_request_id = confirmation_request_id
        if state_snapshot is not None:
            version.state_snapshot = state_snapshot
        if completed:
            version.completed_at = datetime.now(timezone.utc)
        if failed:
            version.failed_at = datetime.now(timezone.utc)

        version.updated_at = datetime.now(timezone.utc)
        await self._session.flush()
        return version
