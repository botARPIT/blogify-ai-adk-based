"""Worker process for blog generation jobs.

Run as: python -m src.workers.blog_worker

NOTE: The Reaper runs as a separate process (`python -m src.workers.reaper`).
Do NOT instantiate Reaper inside this worker — 3 worker replicas would create
3 concurrent reapers all racing to expire/requeue the same stale leases.
"""

import asyncio
import os
import socket
from datetime import UTC, datetime

from src.config.env_config import config
from src.config.logging_config import get_logger, setup_logging
from src.core.database import AsyncSessionFactory
from src.core.redis_pool import get_redis_client
from src.core.task_queue import TaskQueue
from src.models.repositories.session_lease_repository import SessionLeaseRepository
from src.workers.executor import PipelineExecutor

# Reaper is a separate standalone process — do not import here.

setup_logging(
    config.log_level,
    log_format=config.log_format,
    mask_secrets=config.mask_secrets_in_logs,
)
logger = get_logger(__name__)

WORKER_ID = f"worker-{socket.gethostname()}-{os.getpid()}"
MAX_CONCURRENT_JOBS = 3
HEARTBEAT_INTERVAL = 15
LEASE_SECONDS = 300


class BlogWorker:
    def __init__(self) -> None:
        self._queue = TaskQueue()
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENT_JOBS)
        self._running = True

    async def run(self) -> None:
        asyncio.create_task(self._heartbeat_loop())

        while self._running:
            job = await self._queue.dequeue(timeout=5)
            if job is None:
                continue
            asyncio.create_task(self._process_job(job))

    async def _process_job(self, job) -> None:
        async with self._semaphore:
            async with AsyncSessionFactory() as session:
                lease_repo = SessionLeaseRepository(session)
                acquired = await lease_repo.acquire_lease(job.session_id, WORKER_ID, LEASE_SECONDS)
                if not acquired:
                    await self._queue.acknowledge(job)
                    return

                heartbeat_task = asyncio.create_task(
                    self._job_heartbeat(job.session_id, lease_repo)
                )
                try:
                    executor = PipelineExecutor(session)
                    await executor.execute(job)
                    await session.commit()
                    await self._queue.acknowledge(job)
                except Exception as e:
                    await session.rollback()
                    logger.error("job_failed", session_id=job.session_id, error=str(e))
                finally:
                    heartbeat_task.cancel()
                    await lease_repo.release_lease(job.session_id, WORKER_ID)

    async def _job_heartbeat(self, session_id: int, lease_repo: SessionLeaseRepository) -> None:
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            try:
                await lease_repo.heartbeat_lease(session_id, WORKER_ID, extend_seconds=60)
            except Exception:
                pass

    async def _heartbeat_loop(self) -> None:
        redis = await get_redis_client()
        key = f"blogify:worker:{WORKER_ID}"
        while self._running:
            await redis.set(key, datetime.now(UTC).isoformat(), ex=60)
            await asyncio.sleep(HEARTBEAT_INTERVAL)


async def main():
    worker = BlogWorker()
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
