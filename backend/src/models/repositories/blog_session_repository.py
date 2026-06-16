"""BlogSessionRepository — V1 simplified repository."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.orm_models import BlogSession, BlogSessionStatus, SessionLease


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
        idempotency_key: str | None = None,
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

    async def get_by_id(self, session_id: int) -> BlogSession | None:
        result = await self._session.execute(
            select(BlogSession).where(BlogSession.id == session_id)
        )
        return result.scalar_one_or_none()

    async def get_by_id_for_update(self, session_id: int) -> BlogSession | None:
        result = await self._session.execute(
            select(BlogSession).where(BlogSession.id == session_id).with_for_update()
        )
        return result.scalar_one_or_none()

    async def get_by_idempotency_key(self, user_id: int, key: str) -> BlogSession | None:
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
        active = [s.value for s in BlogSessionStatus.active_states()]
        result = await self._session.execute(
            select(BlogSession).where(
                BlogSession.user_id == user_id,
                BlogSession.status.in_(active),
            )
        )
        return len(result.scalars().all())

    async def get_queued_without_active_leases(
        self,
        *,
        older_than_seconds: int = 30,
        limit: int = 100,
    ) -> list[BlogSession]:
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=older_than_seconds)
        active_lease_exists = exists(
            select(SessionLease.id).where(
                SessionLease.blog_session_id == BlogSession.id,
                SessionLease.ended_at.is_(None),
            )
        )

        result = await self._session.execute(
            select(BlogSession)
            .where(
                BlogSession.status == BlogSessionStatus.QUEUED.value,
                BlogSession.updated_at < cutoff,
                ~active_lease_exists,
            )
            .order_by(BlogSession.updated_at.asc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def update_status(
        self,
        session_id: int,
        status: BlogSessionStatus,
        current_stage: str | None = None,
    ) -> None:
        """Update session status with state machine validation."""
        blog_session = await self.get_by_id(session_id)
        if not blog_session:
            return

        # Validate transition against the state machine
        current = BlogSessionStatus(blog_session.status)
        BlogSessionStatus.validate_transition(current, status)

        blog_session.status = status
        if current_stage:
            blog_session.current_stage = current_stage
        blog_session.updated_at = datetime.now(timezone.utc)
        await self._session.flush()

    async def recover_stale_processing_session(
        self,
        session_id: int,
        *,
        current_stage: str | None = "requeued_by_reaper",
    ) -> BlogSession | None:
        """Reaper-only recovery path for dead in-flight work.

        This bypasses the normal public transition validator because stale-lease
        recovery is a separate control path from user/worker workflow moves.
        """
        blog_session = await self.get_by_id(session_id)
        if not blog_session:
            return None

        current = BlogSessionStatus(blog_session.status)
        if current in BlogSessionStatus.terminal_states():
            return blog_session
        if current != BlogSessionStatus.PROCESSING:
            from src.core.errors import InvalidStateTransition

            raise InvalidStateTransition(
                from_status=current.value,
                to_status=BlogSessionStatus.QUEUED.value,
            )

        blog_session.status = BlogSessionStatus.QUEUED
        blog_session.current_stage = current_stage
        blog_session.updated_at = datetime.now(timezone.utc)
        await self._session.flush()
        return blog_session

    async def update_job_phase(self, session_id: int, job_phase: str) -> None:
        """Persist the job phase for reaper recovery."""
        blog_session = await self.get_by_id(session_id)
        if blog_session:
            blog_session.job_phase = job_phase
            blog_session.updated_at = datetime.now(timezone.utc)
            await self._session.flush()

    async def sync_active_version_fields(
        self,
        session_id: int,
        *,
        outline_data: dict | None = None,
        final_content: str | None = None,
        invocation_id: str | None = None,
        confirmation_request_id: str | None = None,
        adk_session_id: str | None = None,
        active_blog_version_id: int | None = None,
    ) -> None:
        blog_session = await self.get_by_id(session_id)
        if not blog_session:
            return

        if outline_data is not None:
            blog_session.outline_data = outline_data
        if final_content is not None:
            blog_session.final_content = final_content
        if invocation_id is not None:
            blog_session.invocation_id = invocation_id
        if confirmation_request_id is not None:
            blog_session.confirmation_request_id = confirmation_request_id
        if adk_session_id is not None:
            blog_session.adk_session_id = adk_session_id
        if active_blog_version_id is not None:
            blog_session.active_blog_version_id = active_blog_version_id

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

    async def increment_reap_count(self, session_id: int) -> int:
        blog_session = await self.get_by_id(session_id)
        if blog_session:
            blog_session.reap_count += 1
            blog_session.updated_at = datetime.now(timezone.utc)
            await self._session.flush()
            return blog_session.reap_count
        return 0

    async def mark_failed(self, session_id: int, reason: str) -> None:
        """Mark session as FAILED with state machine validation."""
        blog_session = await self.get_by_id(session_id)
        if not blog_session:
            return

        # Validate the transition to FAILED
        current = BlogSessionStatus(blog_session.status)
        BlogSessionStatus.validate_transition(current, BlogSessionStatus.FAILED)

        blog_session.status = BlogSessionStatus.FAILED
        blog_session.failure_reason = reason
        blog_session.failed_at = datetime.now(timezone.utc)
        blog_session.updated_at = datetime.now(timezone.utc)
        await self._session.flush()
