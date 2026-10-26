"""Repository for session lease management - append-only audit trail."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.task_queue import BlogJob
from src.models.orm_models import (
    BlogJobPhase,
    BlogSession,
    BlogSessionStatus,
    BlogVersion,
    LeaseEventType,
    SessionLease,
)
from src.models.repositories.blog_session_repository import BlogSessionRepository
from src.models.repositories.blog_version_repository import BlogVersionRepository


@dataclass
class LeaseAcquireResult:
    acquired: bool
    job: BlogJob | None = None
    version_id: int | None = None
    lease_id: int | None = None
    lease_version: int | None = None


class SessionLeaseRepository:
    """Manages session lease lifecycle with append-only audit trail."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._session_repo = BlogSessionRepository(session)
        self._version_repo = BlogVersionRepository(session)

    def session(self) -> AsyncSession:
        return self._session

    async def acquire_lease(
        self, job: BlogJob, worker_id: str, lease_seconds: int = 300
    ) -> LeaseAcquireResult:
        """Acquire a lease after validating session and hydrating the active DB snapshot."""
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=lease_seconds)
        session_model = await self._session_repo.get_by_id_for_update(job.session_id)
        if session_model is None:
            return LeaseAcquireResult(acquired=False)

        current_lease = await self._get_active_lease(job.session_id)
        lease_is_live = bool(
            current_lease
            and current_lease.lease_expires_at
            and current_lease.lease_expires_at > now
        )
        if current_lease and lease_is_live and current_lease.lease_owner != worker_id:
            return LeaseAcquireResult(acquired=False)

        if current_lease and not lease_is_live:
            # The outbox lease is the recovery clock. Once it expires, the
            # session lease must stop blocking the redelivered event too.
            current_lease.ended_at = now
            current_lease.release_reason = LeaseEventType.HEARTBEAT_FAILED
            session_model.status = BlogSessionStatus.QUEUED.value
            session_model.current_stage = "requeued_by_outbox"
            session_model.updated_at = now
            await self._session.flush()

        new_version = (current_lease.lease_version + 1) if current_lease else 1
        active_version = await self._resolve_active_version(session_model)
        self._validate_phase_state(session_model, job.phase, active_version)

        if current_lease and lease_is_live and current_lease.lease_owner == worker_id:
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
            if getattr(result, "rowcount", 0) <= 0:
                return LeaseAcquireResult(acquired=False)
            await self._mark_processing(session_model, active_version, job.phase)
            hydrated_job = self._hydrate_job(
                session_model,
                active_version,
                job.phase,
                lease_owner=worker_id,
                lease_version=current_lease.lease_version,
            )
            await self._session.flush()
            return LeaseAcquireResult(
                acquired=True,
                job=hydrated_job,
                version_id=active_version.id,
                lease_id=current_lease.id,
                lease_version=current_lease.lease_version,
            )

        new_lease = SessionLease(
            blog_session_id=job.session_id,
            lease_owner=worker_id,
            lease_expires_at=expires_at,
            lease_version=new_version,
            last_heartbeat_at=now,
            started_at=now,
            release_reason=LeaseEventType.ACQUIRED,
        )
        self._session.add(new_lease)
        await self._mark_processing(session_model, active_version, job.phase)
        hydrated_job = self._hydrate_job(
            session_model,
            active_version,
            job.phase,
            lease_owner=worker_id,
            lease_version=new_version,
        )
        await self._session.flush()
        return LeaseAcquireResult(
            acquired=True,
            job=hydrated_job,
            version_id=active_version.id,
            lease_id=new_lease.id,
            lease_version=new_version,
        )

    async def release_lease(
        self,
        session_id: int,
        worker_id: str,
        lease_version: int,
    ) -> None:
        """Release the current lease for a session."""
        active_lease = await self._get_active_lease(session_id)
        if (
            active_lease
            and active_lease.lease_owner == worker_id
            and active_lease.lease_version == lease_version
        ):
            active_lease.ended_at = datetime.now(timezone.utc)
            active_lease.release_reason = LeaseEventType.RELEASED
            await self._session.flush()

    async def heartbeat_lease(
        self,
        session_id: int,
        worker_id: str,
        lease_version: int,
        extend_seconds: int = 60,
    ) -> bool:
        """Extend the lease expiry time and update heartbeat."""
        active_lease = await self._get_active_lease(session_id)
        if (
            not active_lease
            or active_lease.lease_owner != worker_id
            or active_lease.lease_version != lease_version
        ):
            return False

        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=extend_seconds)

        active_lease.lease_expires_at = expires_at
        active_lease.last_heartbeat_at = now
        await self._session.flush()
        return True

    async def _get_active_lease(self, session_id: int) -> SessionLease | None:
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

    async def get_lease_history(self, session_id: int) -> list[SessionLease]:
        """Get all lease events for a session (full audit trail)."""
        result = await self._session.execute(
            select(SessionLease)
            .where(SessionLease.blog_session_id == session_id)
            .order_by(SessionLease.started_at)
        )
        return list(result.scalars().all())

    async def get_current_lease(self, session_id: int) -> SessionLease | None:
        """Get the current active lease for a session."""
        return await self._get_active_lease(session_id)

    async def assert_current_lease(
        self,
        *,
        session_id: int,
        lease_owner: str,
        lease_version: int,
    ) -> SessionLease:
        """Lock and verify the exact attempt before it writes workflow output."""
        now = datetime.now(timezone.utc)
        result = await self._session.execute(
            select(SessionLease)
            .where(
                SessionLease.blog_session_id == session_id,
                SessionLease.ended_at.is_(None),
            )
            .order_by(SessionLease.started_at.desc())
            .limit(1)
            .with_for_update()
        )
        lease = result.scalar_one_or_none()
        if (
            lease is None
            or lease.lease_owner != lease_owner
            or lease.lease_version != lease_version
            or lease.lease_expires_at is None
            or lease.lease_expires_at <= now
        ):
            from src.services.exceptions import WorkflowOwnershipLostError

            raise WorkflowOwnershipLostError(
                f"Attempt no longer owns session {session_id} lease {lease_owner}/{lease_version}"
            )
        return lease

    async def _resolve_active_version(
        self,
        session_model: BlogSession,
    ) -> BlogVersion:
        active_version = None
        if session_model.active_blog_version_id:
            active_version = await self._version_repo.get_by_id(
                session_model.active_blog_version_id
            )

        if active_version is None:
            raise ValueError("Active blog version not found")
        return active_version

    def _validate_phase_state(
        self,
        session_model: BlogSession,
        phase: str,
        active_version: BlogVersion,
    ) -> None:
        if session_model.status != BlogSessionStatus.QUEUED.value:
            raise ValueError(
                f"Session {session_model.id} must be QUEUED before acquisition, got {session_model.status}"
            )

        if phase == BlogJobPhase.FRESH_GENERATION.value:
            return

        if phase == BlogJobPhase.RESEARCH_PHASE.value:
            if not active_version.approved_outline and not active_version.outline_data:
                raise ValueError("Approved outline missing for research_phase resume")
            return

        if phase == BlogJobPhase.REVISION.value:
            if not active_version.draft_content and not active_version.final_content:
                raise ValueError("Revision requires an existing draft or final content snapshot")
            return

        raise ValueError(f"Unsupported job phase: {phase}")

    async def _mark_processing(
        self,
        session_model: BlogSession,
        active_version: BlogVersion,
        phase: str,
    ) -> None:
        session_model.status = BlogSessionStatus.PROCESSING.value
        session_model.job_phase = phase
        session_model.current_stage = self._current_stage_for_phase(phase)
        session_model.updated_at = datetime.now(timezone.utc)

        await self._version_repo.update_version_state(
            active_version.id,
            status=BlogSessionStatus.PROCESSING.value,
            job_phase=phase,
            adk_session_id=active_version.adk_session_id or session_model.adk_session_id,
        )
        await self._session.flush()

    def _hydrate_job(
        self,
        session_model: BlogSession,
        active_version: BlogVersion,
        phase: str,
        *,
        lease_owner: str,
        lease_version: int,
    ) -> BlogJob:
        adk_session_id = active_version.adk_session_id or session_model.adk_session_id
        if not adk_session_id:
            raise ValueError(f"Session {session_model.id} has no ADK session id")
        return BlogJob(
            session_id=session_model.id,
            user_id=session_model.user_id,
            adk_session_id=adk_session_id,
            topic=session_model.topic,
            audience=session_model.audience,
            tone=session_model.tone,
            phase=phase,
            approved_outline=active_version.approved_outline or active_version.outline_data,
            feedback_text=active_version.feedback_text,
            state_snapshot=dict(active_version.state_snapshot or {}),
            lease_owner=lease_owner,
            lease_version=lease_version,
        )

    def _current_stage_for_phase(self, phase: str) -> str:
        if phase == BlogJobPhase.FRESH_GENERATION.value:
            return "intent"
        if phase == BlogJobPhase.RESEARCH_PHASE.value:
            return "research"
        return "revision_research"
