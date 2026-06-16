"""Reaper — recovers stale jobs and re-enqueues them for retry.

Run as a standalone process: python -m src.workers.reaper

Exactly ONE reaper should run across the entire cluster. Running multiple
reapers is safe (idempotent DB updates) but wasteful — keep replicas=1 in
the compose/k8s config.
"""

import asyncio
import json

from src.config.logging_config import get_logger
from src.core.database import AsyncSessionFactory
from src.core.task_queue import BlogJob, TaskQueue
from src.models.orm_models import BlogJobPhase, BlogSessionStatus
from src.models.repositories.blog_session_repository import BlogSessionRepository
from src.models.repositories.blog_version_repository import BlogVersionRepository
from src.models.repositories.session_lease_repository import SessionLeaseRepository

logger = get_logger(__name__)

MAX_REAP_COUNT = 3
REAP_INTERVAL_SECONDS = 60
STALE_THRESHOLD_MINUTES = 2


class Reaper:
    def __init__(self, task_queue: TaskQueue) -> None:
        self._queue = task_queue

    async def run_forever(self) -> None:
        while True:
            try:
                await self._reap_stale_leases()
                await self._reap_queue()
                await self._reconcile_queued_sessions()
            except Exception as e:
                logger.error("reaper_cycle_failed", error=str(e))
            await asyncio.sleep(REAP_INTERVAL_SECONDS)

    async def _reap_stale_leases(self) -> None:
        async with AsyncSessionFactory() as session:
            try:
                session_repo = BlogSessionRepository(session)
                version_repo = BlogVersionRepository(session)
                lease_repo = SessionLeaseRepository(session)

                stale_leases = await lease_repo.get_stale_sessions(STALE_THRESHOLD_MINUTES)

                seen_sessions = set()
                unique_leases = []
                for lease in stale_leases:
                    if lease.blog_session_id not in seen_sessions:
                        seen_sessions.add(lease.blog_session_id)
                        unique_leases.append(lease)
                stale_leases = unique_leases

                for lease in stale_leases:
                    await lease_repo.mark_expired(lease.blog_session_id)

                    new_reap_count = await session_repo.increment_reap_count(lease.blog_session_id)
                    session_model = await session_repo.get_by_id(lease.blog_session_id)

                    if not session_model:
                        continue

                    if new_reap_count > MAX_REAP_COUNT:
                        await session_repo.mark_failed(
                            lease.blog_session_id, "max reap count exceeded"
                        )
                        logger.warning(
                            "session_marked_failed",
                            session_id=lease.blog_session_id,
                            reap_count=new_reap_count,
                        )
                    else:
                        recovered_session = await session_repo.recover_stale_processing_session(
                            lease.blog_session_id
                        )
                        if recovered_session is None:
                            continue
                        active_version = await version_repo.get_active_for_session(
                            lease.blog_session_id
                        )
                        job_phase = self._recovery_phase_for_session(
                            recovered_session.job_phase
                            or (active_version.job_phase if active_version else None),
                            recovered_session.current_stage,
                        )
                        job = BlogJob(
                            session_id=recovered_session.id,
                            user_id=recovered_session.user_id,
                            adk_session_id=recovered_session.adk_session_id,
                            topic=recovered_session.topic,
                            audience=recovered_session.audience,
                            tone=recovered_session.tone,
                            phase=job_phase,
                        )
                        await self._queue.enqueue(job)
                        logger.info(
                            "session_requeued",
                            session_id=lease.blog_session_id,
                            reap_count=new_reap_count,
                            previous_worker=lease.lease_owner,
                        )

                await session.commit()

            except Exception as e:
                await session.rollback()
                logger.error("reaper_cycle_db_error", error=str(e))

    async def _reap_queue(self) -> None:
        stale_entries = await self._queue.get_stale_processing_entries()
        if not stale_entries:
            return

        async with AsyncSessionFactory() as session:
            session_repo = BlogSessionRepository(session)
            lease_repo = SessionLeaseRepository(session)
            reclaimed = 0
            cleaned = 0

            for job_json in stale_entries:
                session_id = None
                try:
                    payload = json.loads(job_json)
                    session_id = payload.get("session_id")
                except Exception:
                    pass

                session_model = (
                    await session_repo.get_by_id(session_id) if isinstance(session_id, int) else None
                )
                active_lease = (
                    await lease_repo.get_current_lease(session_id)
                    if isinstance(session_id, int)
                    else None
                )

                should_requeue = (
                    session_model is not None
                    and session_model.status == BlogSessionStatus.QUEUED.value
                    and session_model.current_stage != "requeued_by_reaper"
                    and active_lease is None
                )

                if should_requeue:
                    moved = await self._queue.requeue_processing_entry(job_json)
                    if moved:
                        reclaimed += 1
                        logger.warning("queue_processing_entry_requeued", session_id=session_id)
                    continue

                removed = await self._queue.remove_processing_entry(job_json)
                if removed:
                    cleaned += 1
                    logger.info("queue_processing_entry_cleaned", session_id=session_id)

            if reclaimed > 0:
                logger.info("queue_reclaimed", count=reclaimed)
            if cleaned > 0:
                logger.info("queue_cleaned", count=cleaned)

    async def _reconcile_queued_sessions(self) -> None:
        async with AsyncSessionFactory() as session:
            try:
                session_repo = BlogSessionRepository(session)
                version_repo = BlogVersionRepository(session)
                tracked_session_ids = await self._queue.get_tracked_session_ids()
                queued_sessions = await session_repo.get_queued_without_active_leases()

                requeued = 0
                for session_model in queued_sessions:
                    if session_model.id in tracked_session_ids:
                        continue

                    active_version = await version_repo.get_active_for_session(session_model.id)
                    phase = (
                        session_model.job_phase
                        or (active_version.job_phase if active_version else None)
                        or BlogJobPhase.FRESH_GENERATION.value
                    )
                    job = BlogJob(
                        session_id=session_model.id,
                        user_id=session_model.user_id,
                        adk_session_id=(
                            (active_version.adk_session_id if active_version else None)
                            or session_model.adk_session_id
                        ),
                        topic=session_model.topic,
                        audience=session_model.audience,
                        tone=session_model.tone,
                        phase=phase,
                        feedback_text=active_version.feedback_text if active_version else None,
                    )
                    await self._queue.enqueue(job)
                    tracked_session_ids.add(session_model.id)
                    requeued += 1
                    logger.warning(
                        "queued_session_reconciled",
                        session_id=session_model.id,
                        phase=phase,
                    )

                await session.commit()
                if requeued > 0:
                    logger.info("queued_session_reconciliation_completed", count=requeued)
            except Exception as e:
                await session.rollback()
                logger.error("queued_session_reconciliation_failed", error=str(e))

    def _recovery_phase_for_session(
        self,
        persisted_phase: str | None,
        current_stage: str | None,
    ) -> str:
        if (
            persisted_phase == BlogJobPhase.RESUME_OUTLINE.value
            and current_stage == "research"
        ):
            return BlogJobPhase.RESEARCH_PHASE.value

        return persisted_phase or BlogJobPhase.FRESH_GENERATION.value


async def main() -> None:
    from src.config.env_config import config
    from src.config.logging_config import setup_logging
    from src.core.task_queue import TaskQueue

    setup_logging(
        config.log_level,
        log_format=config.log_format,
        mask_secrets=config.mask_secrets_in_logs,
    )
    logger.info("reaper_starting")
    reaper = Reaper(TaskQueue())
    await reaper.run_forever()


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
