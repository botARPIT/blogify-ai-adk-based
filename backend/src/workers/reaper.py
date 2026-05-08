"""Reaper — recovers stale jobs and re-enqueues them for retry.

Runs as an asyncio task inside blog_worker.py alongside the main loop.
"""
import asyncio
from datetime import datetime, timezone, timedelta

from src.config.logging_config import get_logger
from src.core.database import AsyncSessionFactory
from src.core.task_queue import BlogJob, TaskQueue
from src.models.orm_models import BlogSessionStatus
from src.models.repositories.blog_session_repository import BlogSessionRepository

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
                await self._reap_db_sessions()
                await self._reap_queue()
            except Exception as e:
                logger.error("reaper_cycle_failed", error=str(e))
            await asyncio.sleep(REAP_INTERVAL_SECONDS)

    async def _reap_db_sessions(self) -> None:
        async with AsyncSessionFactory() as session:
            session_repo = BlogSessionRepository(session)
            stale_sessions = await session_repo.get_stale_processing_sessions(
                STALE_THRESHOLD_MINUTES
            )

            for session in stale_sessions:
                new_reap_count = await session_repo.increment_reap_count(session.id)

                if new_reap_count > MAX_REAP_COUNT:
                    await session_repo.mark_failed(
                        session.id, "max reap count exceeded"
                    )
                    logger.warning(
                        "session_marked_failed",
                        session_id=session.id,
                        reap_count=new_reap_count,
                    )
                else:
                    await session_repo.update_status(
                        session.id, BlogSessionStatus.QUEUED
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
                        session_id=session.id,
                        reap_count=new_reap_count,
                    )

    async def _reap_queue(self) -> None:
        reclaimed = await self._queue.reclaim_stale()
        if reclaimed > 0:
            logger.info("queue_reclaimed", count=reclaimed)