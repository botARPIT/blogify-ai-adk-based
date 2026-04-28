"""DB-authoritative job reaper for stale blog sessions.

Ported from infra-learning reaper pattern. Runs as an async background loop
that queries PostgreSQL for processing sessions with stale heartbeats and
reclaims them by resetting status to QUEUED + bumping lease_version.

The database is the single source of truth — Redis is only used to
re-enqueue the job ID for worker pickup.

Flow:
    1. SELECT blog_sessions WHERE status='processing'
       AND last_heartbeat_at < (now - STALE_THRESHOLD)
    2. For each stale session: SELECT FOR UPDATE → reset to QUEUED,
       bump lease_version, clear owned_by
    3. Re-enqueue the canonical_session_id into Redis task queue
    4. Sleep → repeat

This prevents split-brain scenarios: if a reaped worker wakes up and
tries to complete/fail its job, the lease_version check will reject it.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from src.config.logging_config import get_logger
from src.core.task_queue import task_queue
from src.models.orm_models import BlogSession, BlogSessionStatus
from src.models.repositories.blog_session_repository import BlogSessionRepository
from src.models.repository import get_session_factory

logger = get_logger(__name__)

# How long before a processing session is considered stale (seconds).
STALE_THRESHOLD_SECONDS = 120

# How often the reaper runs (seconds).
REAPER_INTERVAL_SECONDS = 30

# Maximum times a session can be reaped before being marked as permanently failed.
MAX_REAP_COUNT = 3


class JobReaper:
    """Async background reaper for stale blog processing sessions.

    Uses PostgreSQL as the authoritative state store. Redis is only
    touched to re-enqueue reclaimed job IDs.
    """

    def __init__(
        self,
        stale_threshold: int = STALE_THRESHOLD_SECONDS,
        interval: int = REAPER_INTERVAL_SECONDS,
        max_reap_count: int = MAX_REAP_COUNT,
    ) -> None:
        self.stale_threshold = stale_threshold
        self.interval = interval
        self.max_reap_count = max_reap_count
        self._task: asyncio.Task | None = None
        self._running = False

    async def start(self) -> None:
        """Start the reaper background loop."""
        if self._task is not None:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info(
            "reaper_started",
            stale_threshold=self.stale_threshold,
            interval=self.interval,
        )

    async def stop(self) -> None:
        """Gracefully stop the reaper."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("reaper_stopped")

    async def _loop(self) -> None:
        """Main reaper loop."""
        while self._running:
            try:
                reaped = await self._reap_cycle()
                if reaped > 0:
                    logger.info("reaper_cycle_complete", reaped=reaped)
            except Exception as e:
                logger.error("reaper_error", error=str(e))
            await asyncio.sleep(self.interval)

    async def _reap_cycle(self) -> int:
        """Run one reap cycle: find stale sessions, reclaim them.

        Returns the number of sessions reclaimed.
        """
        session_factory = get_session_factory()
        reaped = 0

        async with session_factory() as db:
            async with db.begin():
                repo = BlogSessionRepository(db)
                stale_sessions = await repo.find_stale_processing(
                    threshold_seconds=self.stale_threshold,
                )

                for blog_session in stale_sessions:
                    session_id = blog_session.id
                    old_owner = blog_session.owned_by
                    old_lease = blog_session.lease_version

                    # Check if this session has been reaped too many times.
                    # lease_version tracks total claims+reaps, so we use it
                    # as a proxy for reap count.
                    if old_lease >= self.max_reap_count:
                        logger.warning(
                            "reaper_max_reaps_exceeded",
                            session_id=session_id,
                            lease_version=old_lease,
                            owner=old_owner,
                        )
                        # Fail permanently — don't re-enqueue.
                        await repo.update_status(
                            session_id,
                            status=BlogSessionStatus.FAILED,
                            current_stage=blog_session.current_stage,
                        )
                        continue

                    new_lease = await repo.reap_session(session_id)
                    if new_lease is None:
                        # Session was already completed/failed by the worker
                        # between find_stale and reap — that's fine.
                        continue

                    logger.info(
                        "session_reaped",
                        session_id=session_id,
                        old_owner=old_owner,
                        old_lease=old_lease,
                        new_lease=new_lease,
                    )

                    reaped += 1

        # Re-enqueue outside the DB transaction to avoid holding locks
        # during Redis I/O. We query again for freshly QUEUED sessions
        # that have no owner (i.e., just reaped).
        if reaped > 0:
            async with session_factory() as db:
                repo = BlogSessionRepository(db)
                from sqlalchemy import select

                result = await db.execute(
                    select(BlogSession).where(
                        BlogSession.status == BlogSessionStatus.QUEUED,
                        BlogSession.owned_by.is_(None),
                        BlogSession.claimed_at.is_(None),
                    )
                )
                queued_sessions = result.scalars().all()

                for session in queued_sessions:
                    try:
                        await task_queue.enqueue(
                            task_type="blog_generation",
                            payload={
                                "canonical_session_id": session.id,
                                "session_id": str(session.id),
                                "topic": session.topic,
                                "audience": session.audience or "general readers",
                                "user_id": str(session.end_user_id),
                                "job_phase": "outline_gate",
                                "_reaped": True,
                            },
                        )
                        logger.info(
                            "reaped_session_requeued",
                            session_id=session.id,
                        )
                    except Exception as e:
                        logger.error(
                            "reaper_requeue_failed",
                            session_id=session.id,
                            error=str(e),
                        )

        return reaped


# Module-level singleton
job_reaper = JobReaper()
