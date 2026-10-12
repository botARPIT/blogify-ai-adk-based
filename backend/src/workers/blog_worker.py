"""Worker process for blog generation jobs.

Run as: python -m src.workers.blog_worker

NOTE: The Reaper runs as a separate process (`python -m src.workers.reaper`).
Do NOT instantiate Reaper inside this worker — 3 worker replicas would create
3 concurrent reapers all racing to expire/requeue the same stale leases.
"""

import asyncio
import os
import socket
from datetime import datetime, timezone

from src.config.env_config import config
from src.config.logging_config import get_logger, setup_logging
from src.core.database import AsyncSessionFactory
from src.core.redis_pool import get_redis_client
from src.core.task_queue import BlogJob, TaskQueue
from src.models.orm_models import BlogSessionStatus
from src.models.repositories.blog_session_repository import BlogSessionRepository
from src.models.repositories.session_lease_repository import SessionLeaseRepository
from src.models.repositories.workflow_outbox_repository import WorkflowOutboxRepository
from src.workers.executor import PipelineExecutor, RetryableDownstreamError

# Reaper is a separate standalone process — do not import here.

setup_logging(
    config.log_level,
    log_format=config.log_format,
    mask_secrets=config.mask_secrets_in_logs,
)
logger = get_logger(__name__)

WORKER_ID = f"worker-{socket.gethostname()}-{os.getpid()}"
MAX_CONCURRENT_JOBS = 3
HEARTBEAT_INTERVAL = 30
LEASE_SECONDS = 300
class BlogWorker:
    def __init__(self) -> None:
        self._queue = TaskQueue()
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENT_JOBS)
        self._running = True

    async def run(self) -> None:
        asyncio.create_task(self._heartbeat_loop())

        while self._running:
            try:
                job = await self._queue.dequeue_or_wait()
            except Exception as exc:
                logger.warning("redis_queue_wait_failed", error=str(exc))
                await asyncio.sleep(1)
                continue
            await self._start_job(job)

    async def _start_job(self, job: BlogJob) -> None:
        asyncio.create_task(self._process_job(job))

    async def _claim_outbox_event(self, event_id: int) -> dict | None:
        async with AsyncSessionFactory() as session:
            repo = WorkflowOutboxRepository(session)
            event = await repo.claim_event(
                event_id, worker_id=WORKER_ID, lease_seconds=LEASE_SECONDS
            )
            if event is None:
                await session.rollback()
                return None
            payload = dict(event.payload)
            await session.commit()
            return payload

    async def _process_job(self, job: BlogJob, *, outbox_event_id: int | None = None) -> None:
        async with self._semaphore:
            if outbox_event_id is None:
                outbox_event_id = job.outbox_event_id
            if outbox_event_id is not None:
                try:
                    payload = await self._claim_outbox_event(outbox_event_id)
                    if payload is None:
                        await self._queue.acknowledge(job)
                        return
                    job_data = dict(payload["job"])
                    job_data["outbox_event_id"] = outbox_event_id
                    job = BlogJob(**job_data)
                except (KeyError, TypeError, ValueError) as exc:
                    await self._retry_outbox_event(outbox_event_id, f"invalid job payload: {exc}")
                    await self._queue.acknowledge(job)
                    return
            hydrated_job = None
            async with AsyncSessionFactory() as session:
                if outbox_event_id is not None:
                    blog_session = await BlogSessionRepository(session).get_by_id(job.session_id)
                    if blog_session is None or (
                        blog_session.status != BlogSessionStatus.QUEUED.value
                        and blog_session.status != BlogSessionStatus.PROCESSING.value
                    ):
                        await session.rollback()
                        await self._complete_outbox_event(outbox_event_id)
                        await self._queue.acknowledge(job)
                        return
                    if (
                        blog_session.status == BlogSessionStatus.QUEUED.value
                        and blog_session.job_phase != job.phase
                    ):
                        await session.rollback()
                        await self._complete_outbox_event(outbox_event_id)
                        await self._queue.acknowledge(job)
                        return

                lease_repo = SessionLeaseRepository(session)
                acquired = await lease_repo.acquire_lease(job, WORKER_ID, LEASE_SECONDS)
                if not acquired.acquired or acquired.job is None:
                    await session.rollback()
                    if outbox_event_id is None:
                        await self._queue.acknowledge(job)
                    else:
                        await self._retry_outbox_event(
                            outbox_event_id, "session lease is currently held by another worker"
                        )
                    return

                hydrated_job = acquired.job
                try:
                    await session.commit()
                except Exception:
                    await session.rollback()
                    raise

            heartbeat_task = asyncio.create_task(
                self._job_heartbeat(hydrated_job.session_id, outbox_event_id=outbox_event_id)
            )
            try:
                async with AsyncSessionFactory() as session:
                    executor = PipelineExecutor(session)
                    await executor.execute(hydrated_job)
                    if outbox_event_id is not None:
                        await WorkflowOutboxRepository(session).complete(
                            outbox_event_id, worker_id=WORKER_ID
                        )
                    await session.commit()
                if outbox_event_id is None:
                    await self._queue.acknowledge(job)
                else:
                    await self._queue.acknowledge(job)
            except Exception as e:
                logger.error("job_failed", session_id=job.session_id, error=str(e))
                if outbox_event_id is not None:
                    if isinstance(e, RetryableDownstreamError):
                        retried = await self._retry_outbox_event(outbox_event_id, str(e))
                    else:
                        retried = False
                    if not retried:
                        async with AsyncSessionFactory() as session:
                            executor = PipelineExecutor(session)
                            await executor.fail(hydrated_job or job, str(e))
                            await WorkflowOutboxRepository(session).fail(
                                outbox_event_id, worker_id=WORKER_ID, error=str(e)
                            )
                            await session.commit()
                    await self._queue.acknowledge(job)
            finally:
                heartbeat_task.cancel()
                await self._release_lease(hydrated_job.session_id if hydrated_job else job.session_id)

    async def _job_heartbeat(
        self, session_id: int, *, outbox_event_id: int | None = None
    ) -> None:
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            try:
                async with AsyncSessionFactory() as session:
                    lease_repo = SessionLeaseRepository(session)
                    extended = await lease_repo.heartbeat_lease(
                        session_id, WORKER_ID, extend_seconds=90
                    )
                    outbox_extended = False
                    if outbox_event_id is not None:
                        outbox_extended = await WorkflowOutboxRepository(session).heartbeat(
                            outbox_event_id,
                            worker_id=WORKER_ID,
                            lease_seconds=LEASE_SECONDS,
                        )
                    if extended or outbox_extended:
                        await session.commit()
                    else:
                        await session.rollback()
            except Exception:
                pass

    async def _complete_outbox_event(self, event_id: int) -> None:
        async with AsyncSessionFactory() as session:
            repo = WorkflowOutboxRepository(session)
            await repo.complete(event_id, worker_id=WORKER_ID)
            await session.commit()

    async def _retry_outbox_event(self, event_id: int, error: str) -> bool:
        async with AsyncSessionFactory() as session:
            repo = WorkflowOutboxRepository(session)
            retried = await repo.retry(event_id, worker_id=WORKER_ID, error=error)
            await session.commit()
            return retried

    async def _release_lease(self, session_id: int) -> None:
        try:
            async with AsyncSessionFactory() as session:
                lease_repo = SessionLeaseRepository(session)
                await lease_repo.release_lease(session_id, WORKER_ID)
                await session.commit()
        except Exception as exc:
            logger.error("lease_release_failed", session_id=session_id, error=str(exc))

    async def _heartbeat_loop(self) -> None:
        redis = await get_redis_client()
        key = f"blogify:worker:{WORKER_ID}"
        while self._running:
            await redis.set(key, datetime.now(timezone.utc).isoformat(), ex=60)
            await asyncio.sleep(HEARTBEAT_INTERVAL)


async def main():
    worker = BlogWorker()
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
