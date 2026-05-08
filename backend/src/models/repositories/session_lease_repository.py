"""Repository for session lease management - append-only audit trail."""

from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.orm_models import BlogSessionStatus, SessionLease, LeaseEventType


class SessionLeaseRepository:
    """Manages session lease lifecycle with append-only audit trail."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def session(self) -> AsyncSession:
        return self._session

    async def acquire_lease(
        self, session_id: int, worker_id: str, lease_seconds: int = 300
    ) -> bool:
        """Acquire a new lease for a session. Creates a new row (append-only)."""
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=lease_seconds)

        current_lease = await self._get_active_lease(session_id)
        new_version = (current_lease.lease_version + 1) if current_lease else 1

        if current_lease and current_lease.lease_owner == worker_id:
            result = await self._session.execute(
                update(SessionLease)
                .where(
                    SessionLease.id == current_lease.id,
                    SessionLease.lease_owner == worker_id,
                )
                .values(
                    lease_expires_at=expires_at,
                    last_heartbeat_at=now,
                )
            )
            await self._session.flush()
            return result.rowcount > 0

        if current_lease:
            current_lease.ended_at = now
            current_lease.release_reason = LeaseEventType.RELEASED

        new_lease = SessionLease(
            blog_session_id=session_id,
            lease_owner=worker_id,
            lease_expires_at=expires_at,
            lease_version=new_version,
            last_heartbeat_at=now,
            started_at=now,
        )
        self._session.add(new_lease)

        await self._session.execute(
            update(BlogSessionStatus)
            .where(BlogSessionStatus.id == session_id)
            .values(status=BlogSessionStatus.PROCESSING)
        )

        await self._session.flush()
        return True

    async def release_lease(self, session_id: int, worker_id: str) -> None:
        """Release the current lease for a session."""
        active_lease = await self._get_active_lease(session_id)
        if active_lease and active_lease.lease_owner == worker_id:
            active_lease.ended_at = datetime.now(timezone.utc)
            active_lease.release_reason = LeaseEventType.RELEASED
            await self._session.flush()

    async def heartbeat_lease(
        self,
        session_id: int,
        worker_id: str,
        extend_seconds: int = 60,
    ) -> bool:
        """Extend the lease expiry time and update heartbeat."""
        active_lease = await self._get_active_lease(session_id)
        if not active_lease or active_lease.lease_owner != worker_id:
            return False

        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=extend_seconds)

        active_lease.lease_expires_at = expires_at
        active_lease.last_heartbeat_at = now
        await self._session.flush()
        return True

    async def _get_active_lease(self, session_id: int) -> Optional[SessionLease]:
        """Get the most recent non-ended lease for a session."""
        result = await self._session.execute(
            select(SessionLease)
            .where(
                SessionLease.blog_session_id == session_id,
                SessionLease.ended_at.is_(None),
            )
            .order_by(SessionLease.started_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_stale_sessions(
        self, stale_threshold_minutes: int = 10
    ) -> list[SessionLease]:
        """Get all leases that have expired (heartbeat lost)."""
        threshold = datetime.now(timezone.utc) - timedelta(minutes=stale_threshold_minutes)
        result = await self._session.execute(
            select(SessionLease)
            .where(
                SessionLease.ended_at.is_(None),
                SessionLease.lease_expires_at < threshold,
            )
            .order_by(SessionLease.blog_session_id)
        )
        return list(result.scalars().all())

    async def mark_expired(self, session_id: int) -> None:
        """Mark the current lease as expired due to heartbeat failure."""
        active_lease = await self._get_active_lease(session_id)
        if active_lease:
            active_lease.ended_at = datetime.now(timezone.utc)
            active_lease.release_reason = LeaseEventType.HEARTBEAT_FAILED
            await self._session.flush()

    async def get_lease_history(
        self, session_id: int
    ) -> list[SessionLease]:
        """Get all lease events for a session (full audit trail)."""
        result = await self._session.execute(
            select(SessionLease)
            .where(SessionLease.blog_session_id == session_id)
            .order_by(SessionLease.started_at)
        )
        return list(result.scalars().all())

    async def get_current_lease(
        self, session_id: int
    ) -> Optional[SessionLease]:
        """Get the current active lease for a session."""
        return await self._get_active_lease(session_id)