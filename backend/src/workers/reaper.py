"""Reaper — recovers stale jobs and re-enqueues them for retry.

Run as a standalone process: python -m src.workers.reaper

Exactly ONE reaper should run across the entire cluster. Running multiple
reapers is safe (idempotent DB updates) but wasteful — configure one reaper
process in the active deployment runtime.
"""

import asyncio
import json
import os

from prometheus_client import start_http_server

from src.config.logging_config import get_logger
from src.core.database import AsyncSessionFactory
from src.core.task_queue import BlogJob, QueueFullError, TaskQueue
from src.models.orm_models import BlogSessionStatus
from src.models.repositories.blog_session_repository import BlogSessionRepository
from src.models.repositories.workflow_outbox_repository import WorkflowOutboxRepository
from src.monitoring.runtime_metrics import cancel_metrics_task, runtime_metrics_poller
from src.monitoring.tracing import init_tracing, instrument_clients, instrument_database

logger = get_logger(__name__)

REAP_INTERVAL_SECONDS = 180
OUTBOX_RELAY_INTERVAL_SECONDS = 2


class Reaper:
    def __init__(self, task_queue: TaskQueue) -> None:
        self._queue = task_queue

    async def run_forever(self) -> None:
        await asyncio.gather(self._outbox_relay_forever(), self._maintenance_forever())

    async def _maintenance_forever(self) -> None:
        while True:
            try:
                await self._reap_queue()
            except Exception as e:
                logger.error("reaper_cycle_failed", error=str(e))
            await asyncio.sleep(REAP_INTERVAL_SECONDS)

    async def _outbox_relay_forever(self) -> None:
        while True:
            await self._dispatch_outbox_events()
            await asyncio.sleep(OUTBOX_RELAY_INTERVAL_SECONDS)

    async def _dispatch_outbox_events(self) -> None:
        """Relay durable outbox events to Redis; stale markers are republished."""
        async with AsyncSessionFactory() as session:
            try:
                repo = WorkflowOutboxRepository(session)
                exhausted_sessions = await repo.fail_exhausted_expired_claims()
                session_repo = BlogSessionRepository(session)
                for session_id in set(exhausted_sessions):
                    blog_session = await session_repo.get_by_id(session_id)
                    if blog_session and blog_session.status not in {
                        status.value for status in BlogSessionStatus.terminal_states()
                    }:
                        await session_repo.mark_failed(
                            session_id, "worker claim expired after maximum attempts"
                        )
                if exhausted_sessions:
                    await session.commit()

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
                job_data["trace_context"] = payload.get("trace_context")
                await self._queue.enqueue(BlogJob(**job_data))
            except QueueFullError:
                # Keep this and later outbox rows undispatched; retry next relay cycle.
                logger.info("outbox_dispatch_paused_queue_full", event_id=event_id)
                break
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
    from src.core.database import engine
    from src.core.task_queue import TaskQueue

    setup_logging(
        config.log_level,
        log_format=config.log_format,
        mask_secrets=config.mask_secrets_in_logs,
    )
    init_tracing()
    instrument_clients()
    instrument_database(engine)
    server, _ = start_http_server(
        int(os.getenv("REAPER_METRICS_PORT", "9102")), addr="0.0.0.0"
    )
    metrics_task = asyncio.create_task(
        runtime_metrics_poller("reaper", include_shared_state=False)
    )
    logger.info("reaper_starting")
    reaper = Reaper(TaskQueue())
    try:
        await reaper.run_forever()
    finally:
        await cancel_metrics_task(metrics_task)
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
