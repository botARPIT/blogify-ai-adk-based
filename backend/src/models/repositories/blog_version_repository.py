"""BlogVersionRepository — manages BlogVersion records."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.orm_models import (
    BlogCreatedBy,
    BlogEditorStatus,
    BlogVersion,
    BlogVersionSource,
)


class BlogVersionRepository:
    """Create and retrieve BlogVersion records."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        blog_session_id: int,
        source_type: BlogVersionSource,
        content_markdown: Optional[str] = None,
        title: Optional[str] = None,
        word_count: int = 0,
        sources_count: int = 0,
        editor_status: BlogEditorStatus = BlogEditorStatus.DRAFT,
        created_by: BlogCreatedBy = BlogCreatedBy.SYSTEM,
    ) -> BlogVersion:
        # Determine next version number
        next_version = await self._get_next_version_number(blog_session_id)
        version = BlogVersion(
            blog_session_id=blog_session_id,
            version_number=next_version,
            source_type=source_type.value,
            content_markdown=content_markdown,
            title=title,
            word_count=word_count,
            sources_count=sources_count,
            editor_status=editor_status.value,
            created_by=created_by.value,
        )
        self._session.add(version)
        await self._session.flush()
        return version

    async def _get_next_version_number(self, blog_session_id: int) -> int:
        result = await self._session.execute(
            select(BlogVersion.version_number)
            .where(BlogVersion.blog_session_id == blog_session_id)
            .order_by(BlogVersion.version_number.desc())
            .limit(1)
        )
        latest = result.scalar_one_or_none()
        return (latest or 0) + 1

    async def get_by_id(self, version_id: int) -> Optional[BlogVersion]:
        result = await self._session.execute(
            select(BlogVersion).where(BlogVersion.id == version_id)
        )
        return result.scalar_one_or_none()

    async def get_latest_for_session(
        self, blog_session_id: int
    ) -> Optional[BlogVersion]:
        result = await self._session.execute(
            select(BlogVersion)
            .where(BlogVersion.blog_session_id == blog_session_id)
            .order_by(BlogVersion.version_number.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_latest_approved(
        self, blog_session_id: int
    ) -> Optional[BlogVersion]:
        result = await self._session.execute(
            select(BlogVersion)
            .where(
                BlogVersion.blog_session_id == blog_session_id,
                BlogVersion.editor_status == BlogEditorStatus.HUMAN_APPROVED.value,
            )
            .order_by(BlogVersion.version_number.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_all_for_session(self, blog_session_id: int) -> list[BlogVersion]:
        result = await self._session.execute(
            select(BlogVersion)
            .where(BlogVersion.blog_session_id == blog_session_id)
            .order_by(BlogVersion.version_number)
        )
        return list(result.scalars().all())

    async def mark_approved(self, version_id: int) -> None:
        version = await self.get_by_id(version_id)
        if version:
            version.editor_status = BlogEditorStatus.HUMAN_APPROVED.value

    async def mark_rejected(self, version_id: int) -> None:
        version = await self.get_by_id(version_id)
        if version:
            version.editor_status = BlogEditorStatus.HUMAN_REJECTED.value

    async def mark_editor_approved(self, version_id: int) -> None:
        version = await self.get_by_id(version_id)
        if version:
            version.editor_status = BlogEditorStatus.EDITOR_APPROVED.value
