"""BlogSessionRepository — manages BlogSession lifecycle.

All status mutations are guarded by the SagaStateMachine to prevent illegal
state transitions.  Callers that bypass these methods and mutate ``status``
directly will *not* have transition validation — don't do that.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from src.config.logging_config import get_logger
from src.core.saga_state_machine import (
    CANCELLABLE_STAGES,
    SagaStateMachine,
)
from src.models.orm_models import BlogSession, BlogSessionStatus, SessionLease

logger = get_logger(__name__)


class BlogSessionRepository:
    """Create, read, and update BlogSession records."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

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
        """Create a new blog session with atomic per_user_blog_number."""
        for attempt in range(3):
            try:
                next_num = await self._get_next_blog_number(end_user_id)

                blog_session = BlogSession(
                    tenant_id=tenant_id,
                    end_user_id=end_user_id,
                    service_client_id=service_client_id,
                    topic=topic,
                    audience=audience,
                    tone=tone,
                    external_request_id=external_request_id,
                    external_blog_id=external_blog_id,
                    per_user_blog_number=next_num,
                    status=BlogSessionStatus.QUEUED,
                    budget_reserved_usd=budget_reserved_usd,
                    budget_reserved_tokens=budget_reserved_tokens,
                )
                self._session.add(blog_session)
                await self._session.flush()
                return blog_session

            except IntegrityError as e:
                await self._session.rollback()
                logger.warning(
                    "create_blog_session_retry",
                    end_user_id=end_user_id,
                    attempt=attempt + 1,
                    error=str(e),
                )
                continue

        raise Exception("Failed to create blog session after 3 attempts")

    async def _get_next_blog_number(self, end_user_id: int) -> int:
        """Get next blog number for user with FOR UPDATE locking."""
        result = await self._session.execute(
            select(BlogSession.per_user_blog_number)
            .where(BlogSession.end_user_id == end_user_id)
            .order_by(BlogSession.per_user_blog_number.desc())
            .limit(1)
            .with_for_update()
        )
        last = result.scalar_one_or_none()
        return (last or 0) + 1

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    async def get_by_id(self, session_id: int) -> Optional[BlogSession]:
        result = await self._session.execute(
            select(BlogSession).where(BlogSession.id == session_id)
        )
        return result.scalar_one_or_none()

    async def get_by_id_for_update(self, session_id: int) -> Optional[BlogSession]:
        result = await self._session.execute(
            select(BlogSession)
            .where(BlogSession.id == session_id)
            .with_for_update()
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
        result = await self._session.execute(
            select(func.count(BlogSession.id)).where(
                BlogSession.end_user_id == end_user_id,
                BlogSession.status == BlogSessionStatus.PROCESSING.value,
            )
        )
        return int(result.scalar_one() or 0)

    # ------------------------------------------------------------------
    # Status mutations (saga-guarded)
    # ------------------------------------------------------------------

    async def update_status(
        self,
        session_id: int,
        status: BlogSessionStatus,
        current_stage: Optional[str] = None,
        error_message: Optional[str] = None,
        failure_reason: Optional[str] = None,
        lease_version: Optional[int] = None,
    ) -> bool:
        """Update session status with saga transition validation.

        If lease_version is provided, validates that the session hasn't been
        reaped (lease changed) before applying the update. This prevents stale
        workers from overwriting the reaper's state.

        Returns:
            True if update was applied, False if lease mismatch or not found.

        Raises:
            IllegalStateTransition: If the transition violates the saga map.
        """
        blog_session = await self.get_by_id(session_id)
        if not blog_session:
            return False

        if lease_version is not None:
            current_lease = blog_session.lease.lease_version if blog_session.lease else None
            if current_lease != lease_version:
                logger.warning(
                    "update_status_lease_mismatch",
                    session_id=session_id,
                    expected_lease=lease_version,
                    actual_lease=current_lease,
                )
                return False

        # ── Saga guard ──
        SagaStateMachine.validate(blog_session.status, status, session_id)

        blog_session.status = status
        if current_stage is not None:
            blog_session.current_stage = current_stage
        if error_message is not None:
            blog_session.error_message = error_message
        if failure_reason is not None:
            blog_session.failure_reason = failure_reason
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
    # Cancellation (saga-guarded)
    # ------------------------------------------------------------------

    async def cancel_session(
        self,
        session_id: int,
        failure_reason: str = "user_cancelled",
    ) -> bool:
        """Cancel a session if the saga state machine permits it.

        Cancellation policy:
        - QUEUED, AWAITING_OUTLINE_REVIEW, REVISION_REQUESTED → always allowed.
        - PROCESSING → only if current_stage is in {intent, outline, research}.
        - AWAITING_FINAL_REVIEW → blocked (must approve/revise or let it fail).
        - COMPLETED, FAILED, CANCELLED → already terminal.

        Returns:
            True if the session was cancelled, False if not found.

        Raises:
            IllegalStateTransition: If cancellation is not permitted.
        """
        result = await self._session.execute(
            select(BlogSession)
            .where(BlogSession.id == session_id)
            .with_for_update()
        )
        blog_session = result.scalar_one_or_none()

        if blog_session is None:
            return False

        # Check the high-level saga cancellability rule (status + stage).
        if not SagaStateMachine.is_cancellable(
            blog_session.status, blog_session.current_stage
        ):
            # Delegate to validate() to produce a clean error with context.
            SagaStateMachine.validate(
                blog_session.status,
                BlogSessionStatus.CANCELLED,
                session_id,
            )

        # If is_cancellable passed, the transition is legal — but we still
        # call validate() to go through the canonical path.
        SagaStateMachine.validate(
            blog_session.status,
            BlogSessionStatus.CANCELLED,
            session_id,
        )

        now = datetime.now(timezone.utc)
        blog_session.status = BlogSessionStatus.CANCELLED
        blog_session.failure_reason = failure_reason
        blog_session.owned_by = None
        blog_session.claimed_at = None
        blog_session.last_heartbeat_at = None
        blog_session.updated_at = now

        return True

    # ------------------------------------------------------------------
    # Failure (saga-guarded, with reason)
    # ------------------------------------------------------------------

    async def fail_session(
        self,
        session_id: int,
        failure_reason: str,
        error_message: Optional[str] = None,
    ) -> bool:
        """Transition a session to FAILED with a classified reason.

        This is the primary method for recording session failures — it stores
        the ``failure_reason`` alongside the status change so that compensation
        and downstream consumers can distinguish operational from system faults.

        Returns:
            True if the session was failed, False if not found.

        Raises:
            IllegalStateTransition: If the current status cannot transition to FAILED.
        """
        result = await self._session.execute(
            select(BlogSession)
            .where(BlogSession.id == session_id)
            .with_for_update()
        )
        blog_session = result.scalar_one_or_none()

        if blog_session is None:
            return False

        # ── Saga guard ──
        SagaStateMachine.validate(
            blog_session.status,
            BlogSessionStatus.FAILED,
            session_id,
        )

        now = datetime.now(timezone.utc)
        blog_session.status = BlogSessionStatus.FAILED
        blog_session.failure_reason = failure_reason
        if error_message is not None:
            blog_session.error_message = error_message
        blog_session.owned_by = None
        blog_session.claimed_at = None
        blog_session.last_heartbeat_at = None
        blog_session.updated_at = now

        return True

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
        Validates QUEUED → PROCESSING transition via the saga state machine.

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

        # Only claim sessions that are queued, revision-requested, or
        # processing-but-unowned (re-queued after a stale worker was evicted).
        if blog_session.status not in (
            BlogSessionStatus.QUEUED,
            BlogSessionStatus.REVISION_REQUESTED,
            BlogSessionStatus.PROCESSING,
        ):
            return None

        # If already owned by another live worker, reject.
        if (
            blog_session.lease is not None
            and blog_session.lease.owned_by is not None
            and blog_session.lease.owned_by != worker_id
            and blog_session.status == BlogSessionStatus.PROCESSING
        ):
            return None

        # ── Saga guard (QUEUED → PROCESSING) ──
        # Skip validation if already PROCESSING (re-claim after reap).
        if blog_session.status != BlogSessionStatus.PROCESSING:
            SagaStateMachine.validate(
                blog_session.status,
                BlogSessionStatus.PROCESSING,
                session_id,
            )

        now = datetime.now(timezone.utc)

        # Get or create lease
        if blog_session.lease is None:
            lease = SessionLease(
                blog_session_id=session_id,
                lease_version=1,
                owned_by=worker_id,
                claimed_at=now,
                last_heartbeat_at=now,
            )
            self._session.add(lease)
            await self._session.flush()
            new_version = 1
        else:
            blog_session.lease.owned_by = worker_id
            blog_session.lease.claimed_at = now
            blog_session.lease.last_heartbeat_at = now
            blog_session.lease.lease_version += 1
            new_version = blog_session.lease.lease_version

        blog_session.status = BlogSessionStatus.PROCESSING
        blog_session.updated_at = now

        return new_version

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
                BlogSession.lease.has(
                    and_(
                        SessionLease.lease_version == lease_version,
                        SessionLease.owned_by == worker_id,
                    )
                ),
                BlogSession.status == BlogSessionStatus.PROCESSING,
            )
            .with_for_update()
        )
        blog_session = result.scalar_one_or_none()

        if blog_session is None or blog_session.lease is None:
            return False

        blog_session.lease.last_heartbeat_at = datetime.now(timezone.utc)
        return True

    async def complete_with_lease(
        self,
        session_id: int,
        lease_version: int,
        worker_id: str,
    ) -> bool:
        """Mark session completed — only if the lease is still valid.

        Validates the transition via the saga state machine.
        Returns False if a stale worker tries to complete an already-reaped job.
        """
        result = await self._session.execute(
            select(BlogSession)
            .where(
                BlogSession.id == session_id,
                BlogSession.lease.has(
                    and_(
                        SessionLease.lease_version == lease_version,
                        SessionLease.owned_by == worker_id,
                    )
                ),
                BlogSession.status.in_(
                    [
                        BlogSessionStatus.PROCESSING.value,
                        BlogSessionStatus.AWAITING_OUTLINE_REVIEW.value,
                        BlogSessionStatus.AWAITING_FINAL_REVIEW.value,
                    ]
                ),
            )
            .with_for_update()
        )
        blog_session = result.scalar_one_or_none()

        if blog_session is None or blog_session.lease is None:
            return False

        # ── Saga guard ──
        SagaStateMachine.validate(
            blog_session.status,
            BlogSessionStatus.COMPLETED,
            session_id,
        )

        now = datetime.now(timezone.utc)
        blog_session.status = BlogSessionStatus.COMPLETED
        blog_session.completed_at = now
        # Clear lease
        blog_session.lease.owned_by = None
        blog_session.lease.claimed_at = None
        blog_session.lease.last_heartbeat_at = None
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
                BlogSession.lease.has(
                    and_(
                        SessionLease.lease_version == lease_version,
                        SessionLease.owned_by == worker_id,
                    )
                ),
                BlogSession.status.in_(
                    [
                        BlogSessionStatus.AWAITING_OUTLINE_REVIEW.value,
                        BlogSessionStatus.AWAITING_FINAL_REVIEW.value,
                    ]
                ),
            )
            .with_for_update()
        )
        blog_session = result.scalar_one_or_none()
        if blog_session is None or blog_session.lease is None:
            return False

        now = datetime.now(timezone.utc)
        # Clear lease ownership
        blog_session.lease.owned_by = None
        blog_session.lease.claimed_at = None
        blog_session.lease.last_heartbeat_at = None
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
        """Transition a leased processing session into a paused review state.

        Validates PROCESSING → pause-status transition via the saga state machine.
        """
        result = await self._session.execute(
            select(BlogSession)
            .where(
                BlogSession.id == session_id,
                BlogSession.lease.has(
                    and_(
                        SessionLease.lease_version == lease_version,
                        SessionLease.owned_by == worker_id,
                    )
                ),
                BlogSession.status == BlogSessionStatus.PROCESSING,
            )
            .with_for_update()
        )
        blog_session = result.scalar_one_or_none()
        if blog_session is None or blog_session.lease is None:
            return False

        # ── Saga guard ──
        SagaStateMachine.validate(
            BlogSessionStatus.PROCESSING,
            status,
            session_id,
        )

        now = datetime.now(timezone.utc)
        blog_session.status = status
        blog_session.current_stage = current_stage
        # Clear lease ownership
        blog_session.lease.owned_by = None
        blog_session.lease.claimed_at = None
        blog_session.lease.last_heartbeat_at = None
        blog_session.updated_at = now
        return True

    async def fail_with_lease(
        self,
        session_id: int,
        lease_version: int,
        worker_id: str,
        requeue: bool = False,
        failure_reason: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> bool:
        """Mark session failed — only if the lease is still valid.

        If ``requeue`` is True, reset to QUEUED for retry instead of FAILED.
        Returns False if a stale worker tries to mutate an already-reaped job.

        Validates transitions via the saga state machine.
        """
        result = await self._session.execute(
            select(BlogSession)
            .where(
                BlogSession.id == session_id,
                BlogSession.lease.has(
                    and_(
                        SessionLease.lease_version == lease_version,
                        SessionLease.owned_by == worker_id,
                    )
                ),
                BlogSession.status == BlogSessionStatus.PROCESSING,
            )
            .with_for_update()
        )
        blog_session = result.scalar_one_or_none()

        if blog_session is None or blog_session.lease is None:
            return False

        target_status = BlogSessionStatus.QUEUED if requeue else BlogSessionStatus.FAILED

        # ── Saga guard ──
        SagaStateMachine.validate(
            blog_session.status,
            target_status,
            session_id,
        )

        now = datetime.now(timezone.utc)
        if requeue:
            blog_session.status = BlogSessionStatus.QUEUED
            blog_session.lease.lease_version += 1
            # Clear lease ownership
            blog_session.lease.owned_by = None
            blog_session.lease.claimed_at = None
            blog_session.lease.last_heartbeat_at = None
        else:
            blog_session.status = BlogSessionStatus.FAILED
            blog_session.failure_reason = failure_reason
            if error_message is not None:
                blog_session.error_message = error_message
            # Clear lease ownership
            blog_session.lease.owned_by = None
            blog_session.lease.last_heartbeat_at = None
        blog_session.updated_at = now

        return True

    # ------------------------------------------------------------------
    # Stale session reaping
    # ------------------------------------------------------------------

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
            select(BlogSession)
            .join(SessionLease, SessionLease.blog_session_id == BlogSession.id, isouter=True)
            .where(
                BlogSession.status == BlogSessionStatus.PROCESSING,
                or_(
                    and_(
                        SessionLease.last_heartbeat_at.isnot(None),
                        SessionLease.last_heartbeat_at < cutoff,
                    ),
                    and_(
                        SessionLease.owned_by.is_(None),
                        SessionLease.last_heartbeat_at.is_(None),
                        BlogSession.updated_at < cutoff,
                    ),
                ),
            )
        )
        return list(result.scalars().all())

    async def reap_session(self, session_id: int) -> int | None:
        """Reap a stale session: reset to QUEUED, bump lease, clear ownership.

        Uses SELECT FOR UPDATE for atomicity.
        Validates PROCESSING → QUEUED transition via the saga state machine.

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

        # ── Saga guard ──
        SagaStateMachine.validate(
            blog_session.status,
            BlogSessionStatus.QUEUED,
            session_id,
        )

        now = datetime.now(timezone.utc)
        blog_session.status = BlogSessionStatus.QUEUED
        
        # Update lease
        if blog_session.lease:
            blog_session.lease.lease_version += 1
            blog_session.lease.reap_count += 1
            blog_session.lease.owned_by = None
            blog_session.lease.claimed_at = None
            blog_session.lease.last_heartbeat_at = None
        
        blog_session.updated_at = now

        return blog_session.lease.lease_version if blog_session.lease else None
