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
from src.models.repositories.blog_session_repository import BlogSessionRepository
from src.models.repositories.session_lease_repository import SessionLeaseRepository
from src.models.repositories.workflow_outbox_repository import WorkflowOutboxRepository

logger = get_logger(__name__)

MAX_REAP_COUNT = 3
REAP_INTERVAL_SECONDS = 180
OUTBOX_RELAY_INTERVAL_SECONDS = 2
STALE_THRESHOLD_MINUTES = 2


class Reaper:
    def __init__(self, task_queue: TaskQueue) -> None:
        self._queue = task_queue

    async def run_forever(self) -> None:
        await asyncio.gather(self._outbox_relay_forever(), self._maintenance_forever())

    async def _maintenance_forever(self) -> None:
        while True:
            try:
                await self._reap_stale_leases()
                await self._reap_queue()
            except Exception as e:
                logger.error("reaper_cycle_failed", error=str(e))
            await asyncio.sleep(REAP_INTERVAL_SECONDS)

    async def _outbox_relay_forever(self) -> None:
        while True:
            await self._dispatch_outbox_events()
            await asyncio.sleep(OUTBOX_RELAY_INTERVAL_SECONDS)

    async def _reap_stale_leases(self) -> None:
        async with AsyncSessionFactory() as session:
            try:
                session_repo = BlogSessionRepository(session)
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
                        logger.info(
                            "session_recovered_for_outbox_redelivery",
                            session_id=lease.blog_session_id,
                            reap_count=new_reap_count,
                            previous_worker=lease.lease_owner,
                        )

                await session.commit()

            except Exception as e:
                await session.rollback()
                logger.error("reaper_cycle_db_error", error=str(e))

    async def _dispatch_outbox_events(self) -> None:
        """Relay durable outbox events to Redis; stale markers are republished."""
        async with AsyncSessionFactory() as session:
            try:
                repo = WorkflowOutboxRepository(session)
                events = await repo.get_dispatchable()
                pending = [(event.id, dict(event.payload)) for event in events]
                await session.rollback()
            except Exception as exc:
                await session.rollback()
                logger.error("outbox_dispatch_failed", error=str(exc))
                return

        for event_id, payload in pending:
            try:
                job_data = dict(payload["job"])
                job_data["outbox_event_id"] = event_id
                await self._queue.enqueue(BlogJob(**job_data))
            except (KeyError, TypeError, ValueError) as exc:
                logger.error("invalid_outbox_job", event_id=event_id, error=str(exc))
                continue

            async with AsyncSessionFactory() as session:
                try:
                    await WorkflowOutboxRepository(session).mark_dispatched(event_id)
                    await session.commit()
                except Exception as exc:
                    await session.rollback()
                    logger.error("outbox_dispatch_marker_failed", event_id=event_id, error=str(exc))

    async def _reap_queue(self) -> None:
        stale_entries = await self._queue.get_stale_processing_entries()
        cleaned = 0
        for job_json in stale_entries:
            session_id = None
            try:
                payload = json.loads(job_json)
                session_id = payload.get("session_id")
            except Exception:
                pass

            removed = await self._queue.remove_processing_entry(job_json)
            if removed:
                cleaned += 1
                logger.info("queue_processing_entry_cleaned", session_id=session_id)

        if cleaned > 0:
            logger.info("queue_cleaned", count=cleaned)

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
