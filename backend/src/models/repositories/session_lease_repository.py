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
        if current_lease and current_lease.lease_owner != worker_id:
            return LeaseAcquireResult(acquired=False)

        new_version = (current_lease.lease_version + 1) if current_lease else 1
        active_version = await self._resolve_active_version(session_model, job)
        self._validate_phase_state(session_model, job.phase, active_version)

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
            if result.rowcount <= 0:
                return LeaseAcquireResult(acquired=False)
            await self._mark_processing(session_model, active_version, job.phase)
            hydrated_job = self._hydrate_job(session_model, active_version, job.phase)
            await self._session.flush()
            return LeaseAcquireResult(
                acquired=True,
                job=hydrated_job,
                version_id=active_version.id,
                lease_id=current_lease.id,
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
        hydrated_job = self._hydrate_job(session_model, active_version, job.phase)
        await self._session.flush()
        return LeaseAcquireResult(
            acquired=True,
            job=hydrated_job,
            version_id=active_version.id,
            lease_id=new_lease.id,
        )

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

    async def get_stale_sessions(self, stale_threshold_minutes: int = 10) -> list[SessionLease]:
        """Get all leases that have expired (heartbeat lost)."""
        threshold = datetime.now(timezone.utc) - timedelta(minutes=stale_threshold_minutes)
        result = await self._session.execute(
            select(SessionLease)
            .where(
                
                SessionLease.ended_at.is_(None),
                SessionLease.lease_expires_at < threshold,
                BlogSession.status == BlogSessionStatus.PROCESSING
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

    async def _resolve_active_version(
        self,
        session_model: BlogSession,
        job: BlogJob,
    ):
        active_version = None
        if session_model.active_blog_version_id:
            active_version = await self._version_repo.get_by_id(session_model.active_blog_version_id)

        if job.phase == BlogJobPhase.REVISION.value:
            if active_version is None:
                raise ValueError("Revision requested without an active blog version")
            active_version = await self._version_repo.create_revision_from_active(
                blog_session=session_model,
                active_version=active_version,
                feedback_text=job.feedback_text,
            )
            await self._session_repo.sync_active_version_fields(
                session_model.id,
                active_blog_version_id=active_version.id,
                outline_data=active_version.outline_data,
                invocation_id=active_version.invocation_id,
                confirmation_request_id=active_version.confirmation_request_id,
                adk_session_id=active_version.adk_session_id,
            )
            return active_version

        if active_version is None:
            raise ValueError("Active blog version not found")
        return active_version

    def _validate_phase_state(self, session_model: BlogSession, phase: str, active_version) -> None:
        if session_model.status != BlogSessionStatus.QUEUED.value:
            raise ValueError(
                f"Session {session_model.id} must be QUEUED before acquisition, got {session_model.status}"
            )

        if phase == BlogJobPhase.FRESH_GENERATION.value:
            return

        if phase == BlogJobPhase.RESUME_OUTLINE.value:
            if not active_version.approved_outline and not active_version.outline_data:
                raise ValueError("Approved outline missing for resume_outline")
            if not active_version.invocation_id or not active_version.confirmation_request_id:
                raise ValueError("Outline resume metadata missing")
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

    async def _mark_processing(self, session_model: BlogSession, active_version, phase: str) -> None:
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

    def _hydrate_job(self, session_model: BlogSession, active_version, phase: str) -> BlogJob:
        return BlogJob(
            session_id=session_model.id,
            user_id=session_model.user_id,
            adk_session_id=active_version.adk_session_id or session_model.adk_session_id,
            topic=session_model.topic,
            audience=session_model.audience,
            tone=session_model.tone,
            phase=phase,
            invocation_id=active_version.invocation_id,
            confirmation_request_id=active_version.confirmation_request_id,
            approved_outline=active_version.approved_outline or active_version.outline_data,
            feedback_text=active_version.feedback_text,
        )

    def _current_stage_for_phase(self, phase: str) -> str:
        if phase == BlogJobPhase.FRESH_GENERATION.value:
            return "intent"
        if phase in {BlogJobPhase.RESUME_OUTLINE.value, BlogJobPhase.RESEARCH_PHASE.value}:
            return "research"
        return "revision_research"
