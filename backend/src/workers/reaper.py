"""Reaper — recovers stale jobs and re-enqueues them for retry.

Run as a standalone process: python -m src.workers.reaper

Exactly ONE reaper should run across the entire cluster. Running multiple
reapers is safe (idempotent DB updates) but wasteful — keep replicas=1 in
the compose/k8s config.
"""
import asyncio
from datetime import datetime, timezone, timedelta

from src.config.logging_config import get_logger
from src.core.database import AsyncSessionFactory
from src.core.task_queue import BlogJob, TaskQueue
from src.models.orm_models import BlogSessionStatus
from src.models.repositories.blog_session_repository import BlogSessionRepository
from src.models.repositories.session_lease_repository import SessionLeaseRepository
from src.models.orm_models import LeaseEventType

logger = get_logger(__name__)

MAX_REAP_COUNT = 3
REAP_INTERVAL_SECONDS = 60
STALE_THRESHOLD_MINUTES = 10


class Reaper:
    def __init__(self, task_queue: TaskQueue) -> None:
        self._queue = task_queue

    async def run_forever(self) -> None:
        while True:
            try:
                await self._reap_stale_leases()
                await self._reap_queue()
            except Exception as e:
                logger.error("reaper_cycle_failed", error=str(e))
            await asyncio.sleep(REAP_INTERVAL_SECONDS)

    async def _reap_stale_leases(self) -> None:
        async with AsyncSessionFactory() as session:
            session_repo = BlogSessionRepository(session)
            lease_repo = SessionLeaseRepository(session)

            stale_leases = await lease_repo.get_stale_sessions(STALE_THRESHOLD_MINUTES)

            for lease in stale_leases:
                await lease_repo.mark_expired(lease.blog_session_id)

                new_reap_count = await session_repo.increment_reap_count(lease.blog_session_id)
                session = await session_repo.get_by_id(lease.blog_session_id)

                if not session:
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
                    await session_repo.update_status(
                        lease.blog_session_id, BlogSessionStatus.QUEUED
                    )
                    job = BlogJob(
                        session_id=session.id,
                        user_id=session.user_id,
                        adk_session_id=session.adk_session_id,
                        topic=session.topic,
                        audience=session.audience,
                        tone=session.tone,
                        phase="start",
                    )
                    await self._queue.enqueue(job)
                    logger.info(
                        "session_requeued",
                        session_id=lease.blog_session_id,
                        reap_count=new_reap_count,
                        previous_worker=lease.lease_owner,
                    )

    async def _reap_queue(self) -> None:
        reclaimed = await self._queue.reclaim_stale()
        if reclaimed > 0:
            logger.info("queue_reclaimed", count=reclaimed)


async def main() -> None:
    from src.config.env_loader import ensure_env_loaded  # noqa: F401
    from src.config.logging_config import setup_logging
    from src.config.env_config import config
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