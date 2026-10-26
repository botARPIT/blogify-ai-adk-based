"""Queue consumer for blog-generation workflow attempts."""

import asyncio
import json
import os
import socket
from datetime import datetime, timezone

from prometheus_client import start_http_server

from src.config.env_config import config
from src.config.logging_config import get_logger, setup_logging
from src.core.database import engine
from src.core.redis_pool import get_redis_client
from src.core.task_queue import BlogJob, TaskQueue
from src.monitoring.metrics import queue_wait_failures_total, worker_capacity
from src.monitoring.runtime_metrics import cancel_metrics_task, runtime_metrics_poller
from src.monitoring.tracing import init_tracing, instrument_clients, instrument_database
from src.workers.job_attempt_processor import HEARTBEAT_INTERVAL, WorkflowAttemptProcessor

setup_logging(
    config.log_level,
    log_format=config.log_format,
    mask_secrets=config.mask_secrets_in_logs,
)
logger = get_logger(__name__)

WORKER_ID = f"worker-{socket.gethostname()}-{os.getpid()}"
MAX_CONCURRENT_JOBS = 3


class BlogWorker:
    """Read Redis deliveries and delegate each durable attempt to a processor."""

    def __init__(self) -> None:
        self._queue = TaskQueue()
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENT_JOBS)
        self._attempts = WorkflowAttemptProcessor(self._queue, WORKER_ID)
        self._running = True
        self._active_jobs = 0
        worker_capacity.set(MAX_CONCURRENT_JOBS)

    async def run(self) -> None:
        asyncio.create_task(self._heartbeat_loop())
        while self._running:
            try:
                job = await self._queue.dequeue_or_wait()
            except Exception as exc:
                queue_wait_failures_total.inc()
                logger.warning("redis_queue_wait_failed", error=str(exc))
                await asyncio.sleep(1)
                continue
            await self._start_job(job)

    async def _start_job(self, job: BlogJob) -> None:
        asyncio.create_task(self._process_job(job))

    async def _process_job(self, job: BlogJob) -> None:
        async with self._semaphore:
            self._active_jobs += 1
            try:
                await self._attempts.process(job)
            finally:
                self._active_jobs -= 1

    async def _heartbeat_loop(self) -> None:
        redis = await get_redis_client()
        key = f"blogify:worker:{WORKER_ID}"
        while self._running:
            await redis.set(
                key,
                json.dumps(
                    {
                        "heartbeat_at": datetime.now(timezone.utc).isoformat(),
                        "active_jobs": self._active_jobs,
                        "capacity": MAX_CONCURRENT_JOBS,
                    }
                ),
                ex=60,
            )
            await asyncio.sleep(HEARTBEAT_INTERVAL)


async def main() -> None:
    init_tracing()
    instrument_clients()
    instrument_database(engine)
    server, _ = start_http_server(
        int(os.getenv("WORKER_METRICS_PORT", "9101")), addr="0.0.0.0"
    )
    metrics_task = asyncio.create_task(
        runtime_metrics_poller("worker", include_shared_state=False)
    )
    try:
        await BlogWorker().run()
    finally:
        await cancel_metrics_task(metrics_task)
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    asyncio.run(main())
