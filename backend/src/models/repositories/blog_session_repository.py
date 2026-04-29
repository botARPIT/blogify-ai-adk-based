"""BlogSessionRepository — manages BlogSession lifecycle."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import and_, func, or_, select
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
            status=BlogSessionStatus.QUEUED,
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

    async def list_for_end_user(
        self,
        end_user_id: int,
        limit: int = 20,
        offset: int = 0,
        status: str | None = None,
    ) -> list[BlogSession]:
        stmt = (
            select(BlogSession)
            .where(BlogSession.end_user_id == end_user_id)
            .order_by(BlogSession.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        if status:
            stmt = stmt.where(BlogSession.status == status)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def count_for_end_user(
        self,
        end_user_id: int,
        status: str | None = None,
    ) -> int:
        stmt = select(func.count(BlogSession.id)).where(BlogSession.end_user_id == end_user_id)
        if status:
            stmt = stmt.where(BlogSession.status == status)
        result = await self._session.execute(stmt)
        return int(result.scalar_one() or 0)

    async def count_active_for_end_user(self, end_user_id: int) -> int:
        active_statuses = [
            BlogSessionStatus.QUEUED.value,
            BlogSessionStatus.PROCESSING.value,
            BlogSessionStatus.AWAITING_OUTLINE_REVIEW.value,
            BlogSessionStatus.AWAITING_HUMAN_REVIEW.value,
            BlogSessionStatus.REVISION_REQUESTED.value,
        ]
        result = await self._session.execute(
            select(func.count(BlogSession.id)).where(
                BlogSession.end_user_id == end_user_id,
                BlogSession.status.in_(active_statuses),
            )
        )
        return int(result.scalar_one() or 0)

    async def update_status(
        self,
        session_id: int,
        status: BlogSessionStatus,
        current_stage: Optional[str] = None,
        error_message: Optional[str] = None,
        lease_version: Optional[int] = None,
    ) -> bool:
        """Update session status.
        
        If lease_version is provided, validates that the session hasn't been
        reaped (lease changed) before applying the update. This prevents stale
        workers from overwriting the reaper's state.
        
        Returns:
            True if update was applied, False if lease mismatch (session was reaped).
        """
        blog_session = await self.get_by_id(session_id)
        if not blog_session:
            return False
        
        if lease_version is not None and blog_session.lease_version != lease_version:
            logger.warning(
                "update_status_lease_mismatch",
                session_id=session_id,
                expected_lease=lease_version,
                actual_lease=blog_session.lease_version,
            )
            return False
        
        blog_session.status = status
        if current_stage is not None:
            blog_session.current_stage = current_stage
        if error_message is not None:
            blog_session.error_message = error_message
        blog_session.updated_at = datetime.now(timezone.utc)
        if status == BlogSessionStatus.COMPLETED:
            blog_session.completed_at = datetime.now(timezone.utc)
        return True

    async def update_outline(
        self,
        session_id: int,
        outline_data: dict,
        outline_feedback: Optional[str] = None,
    ) -> None:
        blog_session = await self.get_by_id(session_id)
        if blog_session:
            blog_session.outline_data = outline_data
            blog_session.outline_feedback = outline_feedback
            blog_session.updated_at = datetime.now(timezone.utc)

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

    # ------------------------------------------------------------------
    # Lease-based ownership (DB-authoritative reaper support)
    # ------------------------------------------------------------------

    async def claim_session(
        self,
        session_id: int,
        worker_id: str,
    ) -> int | None:
        """Atomically claim a session for processing.

        Uses SELECT FOR UPDATE to prevent race conditions.

        Returns:
            The new lease_version on success, or None if the session
            cannot be claimed (already owned / wrong status).
        """
        result = await self._session.execute(
            select(BlogSession)
            .where(BlogSession.id == session_id)
            .with_for_update()
        )
        blog_session = result.scalar_one_or_none()

        if blog_session is None:
            return None

        # Only claim sessions that are queued (fresh) or processing-but-unowned
        # (re-queued by reaper after a stale worker was evicted).
        if blog_session.status not in (
            BlogSessionStatus.QUEUED,
            BlogSessionStatus.PROCESSING,
        ):
            return None

        # If already owned by another live worker, reject.
        if (
            blog_session.owned_by is not None
            and blog_session.owned_by != worker_id
            and blog_session.status == BlogSessionStatus.PROCESSING
        ):
            return None

        now = datetime.now(timezone.utc)
        blog_session.status = BlogSessionStatus.PROCESSING
        blog_session.owned_by = worker_id
        blog_session.claimed_at = now
        blog_session.last_heartbeat_at = now
        blog_session.lease_version += 1
        blog_session.updated_at = now

        return blog_session.lease_version

    async def heartbeat(
        self,
        session_id: int,
        lease_version: int,
        worker_id: str,
    ) -> bool:
        """Update heartbeat timestamp for a leased session.

        Returns False if the lease is stale (reaper took it).
        Uses FOR UPDATE to prevent race with concurrent reaper.
        """
        result = await self._session.execute(
            select(BlogSession)
            .where(
                BlogSession.id == session_id,
                BlogSession.lease_version == lease_version,
                BlogSession.owned_by == worker_id,
                BlogSession.status == BlogSessionStatus.PROCESSING,
            )
            .with_for_update()
        )
        blog_session = result.scalar_one_or_none()

        if blog_session is None:
            return False

        blog_session.last_heartbeat_at = datetime.now(timezone.utc)
        return True

    async def complete_with_lease(
        self,
        session_id: int,
        lease_version: int,
        worker_id: str,
    ) -> bool:
        """Mark session completed — only if the lease is still valid.

        Returns False if a stale worker tries to complete an already-reaped job.
        """
        result = await self._session.execute(
            select(BlogSession)
            .where(
                BlogSession.id == session_id,
                BlogSession.lease_version == lease_version,
                BlogSession.owned_by == worker_id,
                BlogSession.status.in_(
                    [
                        BlogSessionStatus.PROCESSING.value,
                        BlogSessionStatus.AWAITING_OUTLINE_REVIEW.value,
                        BlogSessionStatus.AWAITING_HUMAN_REVIEW.value,
                    ]
                ),
            )
            .with_for_update()
        )
        blog_session = result.scalar_one_or_none()

        if blog_session is None:
            return False

        now = datetime.now(timezone.utc)
        if blog_session.status in (
            BlogSessionStatus.PROCESSING.value,
            BlogSessionStatus.PROCESSING,
        ):
            blog_session.status = BlogSessionStatus.COMPLETED
            blog_session.completed_at = now
        blog_session.owned_by = None
        blog_session.claimed_at = None
        blog_session.last_heartbeat_at = None
        blog_session.updated_at = now

        return True

    async def release_lease_for_pause(
        self,
        session_id: int,
        lease_version: int,
        worker_id: str,
    ) -> bool:
        """Clear ownership for a valid paused review state without completing it."""
        result = await self._session.execute(
            select(BlogSession)
            .where(
                BlogSession.id == session_id,
                BlogSession.lease_version == lease_version,
                BlogSession.owned_by == worker_id,
                BlogSession.status.in_(
                    [
                        BlogSessionStatus.AWAITING_OUTLINE_REVIEW.value,
                        BlogSessionStatus.AWAITING_HUMAN_REVIEW.value,
                    ]
                ),
            )
            .with_for_update()
        )
        blog_session = result.scalar_one_or_none()
        if blog_session is None:
            return False

        now = datetime.now(timezone.utc)
        blog_session.owned_by = None
        blog_session.claimed_at = None
        blog_session.last_heartbeat_at = None
        blog_session.updated_at = now
        return True

    async def pause_with_lease(
        self,
        session_id: int,
        lease_version: int,
        worker_id: str,
        status: BlogSessionStatus,
        current_stage: str,
    ) -> bool:
        """Transition a leased processing session into a paused review state."""
        result = await self._session.execute(
            select(BlogSession)
            .where(
                BlogSession.id == session_id,
                BlogSession.lease_version == lease_version,
                BlogSession.owned_by == worker_id,
                BlogSession.status == BlogSessionStatus.PROCESSING,
            )
            .with_for_update()
        )
        blog_session = result.scalar_one_or_none()
        if blog_session is None:
            return False

        now = datetime.now(timezone.utc)
        blog_session.status = status
        blog_session.current_stage = current_stage
        blog_session.owned_by = None
        blog_session.claimed_at = None
        blog_session.last_heartbeat_at = None
        blog_session.updated_at = now
        return True

    async def fail_with_lease(
        self,
        session_id: int,
        lease_version: int,
        worker_id: str,
        requeue: bool = False,
    ) -> bool:
        """Mark session failed — only if the lease is still valid.

        If ``requeue`` is True, reset to QUEUED for retry instead of FAILED.
        Returns False if a stale worker tries to mutate an already-reaped job.
        """
        result = await self._session.execute(
            select(BlogSession)
            .where(
                BlogSession.id == session_id,
                BlogSession.lease_version == lease_version,
                BlogSession.owned_by == worker_id,
                BlogSession.status == BlogSessionStatus.PROCESSING,
            )
            .with_for_update()
        )
        blog_session = result.scalar_one_or_none()

        if blog_session is None:
            return False

        now = datetime.now(timezone.utc)
        if requeue:
            blog_session.status = BlogSessionStatus.QUEUED
            blog_session.lease_version += 1
            blog_session.owned_by = None
            blog_session.claimed_at = None
            blog_session.last_heartbeat_at = None
        else:
            blog_session.status = BlogSessionStatus.FAILED
            blog_session.owned_by = None
            blog_session.last_heartbeat_at = None
        blog_session.updated_at = now

        return True

    async def find_stale_processing(
        self,
        threshold_seconds: int = 120,
    ) -> list[BlogSession]:
        """Find processing sessions whose heartbeat has gone stale.

        Returns stale owned sessions and orphaned processing sessions.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(
            seconds=threshold_seconds
        )
        result = await self._session.execute(
            select(BlogSession).where(
                BlogSession.status == BlogSessionStatus.PROCESSING,
                or_(
                    and_(
                        BlogSession.last_heartbeat_at.isnot(None),
                        BlogSession.last_heartbeat_at < cutoff,
                    ),
                    and_(
                        BlogSession.owned_by.is_(None),
                        BlogSession.last_heartbeat_at.is_(None),
                        BlogSession.updated_at < cutoff,
                    ),
                ),
            )
        )
        return list(result.scalars().all())

    async def reap_session(self, session_id: int) -> int | None:
        """Reap a stale session: reset to QUEUED, bump lease, clear ownership.

        Uses SELECT FOR UPDATE for atomicity.

        Returns:
            The new lease_version, or None if the session is no longer reapable.
        """
        result = await self._session.execute(
            select(BlogSession)
            .where(BlogSession.id == session_id)
            .with_for_update()
        )
        blog_session = result.scalar_one_or_none()

        if blog_session is None:
            return None

        # Only reap sessions that are still processing.
        if blog_session.status != BlogSessionStatus.PROCESSING:
            return None

        now = datetime.now(timezone.utc)
        blog_session.status = BlogSessionStatus.QUEUED
        blog_session.lease_version += 1
        blog_session.reap_count += 1
        blog_session.owned_by = None
        blog_session.claimed_at = None
        blog_session.last_heartbeat_at = None
        blog_session.updated_at = now

        return blog_session.lease_version
