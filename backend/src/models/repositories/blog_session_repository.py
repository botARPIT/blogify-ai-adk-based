"""BlogSessionRepository — V1 simplified repository."""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.orm_models import BlogSession, BlogSessionStatus


class BlogSessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @property
    def session(self) -> AsyncSession:
        return self._session

    async def create(
        self,
        *,
        user_id: int,
        topic: str,
        audience: str,
        tone: str,
        adk_session_id: str,
        idempotency_key: Optional[str] = None,
    ) -> BlogSession:
        blog_session = BlogSession(
            user_id=user_id,
            topic=topic,
            audience=audience,
            tone=tone,
            status=BlogSessionStatus.QUEUED,
            adk_session_id=adk_session_id,
            idempotency_key=idempotency_key,
        )
        self._session.add(blog_session)
        await self._session.flush()
        return blog_session

    async def get_by_id(self, session_id: int) -> Optional[BlogSession]:
        result = await self._session.execute(
            select(BlogSession).where(BlogSession.id == session_id)
        )
        return result.scalar_one_or_none()

    async def get_by_idempotency_key(
        self, user_id: int, key: str
    ) -> Optional[BlogSession]:
        result = await self._session.execute(
            select(BlogSession).where(
                BlogSession.user_id == user_id,
                BlogSession.idempotency_key == key,
            )
        )
        return result.scalar_one_or_none()

    async def get_for_user(self, user_id: int, limit: int = 20) -> list[BlogSession]:
        result = await self._session.execute(
            select(BlogSession)
            .where(BlogSession.user_id == user_id)
            .order_by(BlogSession.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def count_active_for_user(self, user_id: int) -> int:
        result = await self._session.execute(
            select(BlogSession)
            .where(
                BlogSession.user_id == user_id,
                BlogSession.status.in_(
                    [
                        BlogSessionStatus.QUEUED,
                        BlogSessionStatus.PROCESSING,
                        BlogSessionStatus.AWAITING_OUTLINE_REVIEW,
                        BlogSessionStatus.AWAITING_FINAL_REVIEW,
                    ]
                ),
            )
        )
        return len(result.scalars().all())

    async def update_status(
        self,
        session_id: int,
        status: BlogSessionStatus,
        current_stage: Optional[str] = None,
    ) -> None:
        blog_session = await self.get_by_id(session_id)
        if blog_session:
            blog_session.status = status
            if current_stage:
                blog_session.current_stage = current_stage
            blog_session.updated_at = datetime.now(timezone.utc)
            await self._session.flush()

    async def save_outline(
        self,
        session_id: int,
        outline_data: dict,
        invocation_id: str,
        confirmation_request_id: str,
    ) -> None:
        blog_session = await self.get_by_id(session_id)
        if blog_session:
            blog_session.outline_data = outline_data
            blog_session.invocation_id = invocation_id
            blog_session.confirmation_request_id = confirmation_request_id
            blog_session.updated_at = datetime.now(timezone.utc)
            await self._session.flush()

    async def save_final_content(self, session_id: int, content: str) -> None:
        blog_session = await self.get_by_id(session_id)
        if blog_session:
            blog_session.final_content = content
            blog_session.updated_at = datetime.now(timezone.utc)
            await self._session.flush()

    async def acquire_lease(
        self, session_id: int, worker_id: str, lease_seconds: int = 300
    ) -> bool:
        now = datetime.now(timezone.utc)
        expires_at = now.timestamp() + lease_seconds

        result = await self._session.execute(
            update(BlogSession)
            .where(
                BlogSession.id == session_id,
                BlogSession.lease_version == BlogSession.lease_version,
                BlogSession.status.in_([BlogSessionStatus.QUEUED, BlogSessionStatus.PROCESSING]),
            )
            .values(
                lease_owner=worker_id,
                lease_expires_at=datetime.fromtimestamp(expires_at, tz=timezone.utc),
                lease_version=BlogSession.lease_version + 1,
                last_heartbeat_at=now,
                status=BlogSessionStatus.PROCESSING,
            )
        )
        await self._session.flush()
        return result.rowcount > 0

    async def release_lease(self, session_id: int, worker_id: str) -> None:
        blog_session = await self.get_by_id(session_id)
        if blog_session and blog_session.lease_owner == worker_id:
            blog_session.lease_owner = None
            blog_session.lease_expires_at = None
            blog_session.updated_at = datetime.now(timezone.utc)
            await self._session.flush()

    async def heartbeat_lease(
        self,
        session_id: int,
        worker_id: str,
        extend_seconds: int = 60,
    ) -> None:
        now = datetime.now(timezone.utc)
        expires_at = now.timestamp() + extend_seconds

        result = await self._session.execute(
            update(BlogSession)
            .where(
                BlogSession.id == session_id,
                BlogSession.lease_owner == worker_id,
            )
            .values(
                lease_expires_at=datetime.fromtimestamp(expires_at, tz=timezone.utc),
                last_heartbeat_at=now,
            )
        )
        await self._session.flush()

    async def get_stale_processing_sessions(
        self, stale_threshold_minutes: int = 10
    ) -> list[BlogSession]:
        from datetime import timedelta

        threshold = datetime.now(timezone.utc) - timedelta(minutes=stale_threshold_minutes)
        result = await self._session.execute(
            select(BlogSession).where(
                BlogSession.status == BlogSessionStatus.PROCESSING,
                BlogSession.lease_expires_at < threshold,
            )
        )
        return list(result.scalars().all())

    async def increment_reap_count(self, session_id: int) -> int:
        blog_session = await self.get_by_id(session_id)
        if blog_session:
            blog_session.reap_count += 1
            blog_session.updated_at = datetime.now(timezone.utc)
            await self._session.flush()
            return blog_session.reap_count
        return 0

    async def mark_failed(self, session_id: int, reason: str) -> None:
        blog_session = await self.get_by_id(session_id)
        if blog_session:
            blog_session.status = BlogSessionStatus.FAILED
            blog_session.failure_reason = reason
            blog_session.failed_at = datetime.now(timezone.utc)
            blog_session.updated_at = datetime.now(timezone.utc)
            await self._session.flush()