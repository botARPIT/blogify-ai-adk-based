"""Redis task queue with atomic dequeue using Lua script."""

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime

from src.config.logging_config import get_logger
from src.core.redis_pool import get_redis_client

logger = get_logger(__name__)


@dataclass
class BlogJob:
    session_id: int
    user_id: int
    adk_session_id: str
    topic: str
    audience: str
    tone: str
    phase: str
    invocation_id: str | None = None
    confirmation_request_id: str | None = None
    approved_outline: dict | None = None
    feedback_text: str | None = None
    enqueued_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class TaskQueue:
    QUEUE_KEY = "blogify:tasks"
    PROCESSING_KEY = "blogify:processing"
    VISIBILITY_TIMEOUT_SECONDS = 300

    DEQUEUE_SCRIPT = """
    local job = redis.call('RPOP', KEYS[1])
    if not job then return nil end
    redis.call('ZADD', KEYS[2], ARGV[1], job)
    return job
    """

    def __init__(self):
        self._dequeue_script_sha: str | None = None

    async def _get_script_sha(self) -> str:
        if self._dequeue_script_sha is None:
            client = await get_redis_client()
            self._dequeue_script_sha = await client.script_load(self.DEQUEUE_SCRIPT)
        return self._dequeue_script_sha

    async def enqueue(self, job: BlogJob) -> None:
        client = await get_redis_client()
        job_json = json.dumps(job.__dict__)
        await client.lpush(self.QUEUE_KEY, job_json)
        logger.info("job_enqueued", session_id=job.session_id, phase=job.phase)

    async def dequeue(self, timeout: int = 5) -> BlogJob | None:
        client = await get_redis_client()

        deadline = datetime.now(UTC).timestamp() + self.VISIBILITY_TIMEOUT_SECONDS

        try:
            result = await client.evalsha(
                self._dequeue_script_sha or await self._get_script_sha(),
                2,
                self.QUEUE_KEY,
                self.PROCESSING_KEY,
                deadline,
            )
        except Exception:
            client = await get_redis_client()
            result = await client.eval(
                self.DEQUEUE_SCRIPT,
                2,
                self.QUEUE_KEY,
                self.PROCESSING_KEY,
                deadline,
            )

        if result is None:
            return None

        job_data = json.loads(result)
        logger.info("job_dequeued", session_id=job_data.get("session_id"))
        return BlogJob(**job_data)

    async def acknowledge(self, job: BlogJob) -> None:
        client = await get_redis_client()
        job_json = json.dumps(job.__dict__)
        await client.zrem(self.PROCESSING_KEY, job_json)
        logger.info("job_acknowledged", session_id=job.session_id)

    async def reclaim_stale(self) -> int:
        client = await get_redis_client()
        now = datetime.now(UTC).timestamp()

        stale_jobs = await client.zrangebyscore(
            self.PROCESSING_KEY,
            "-inf",
            now,
        )

        reclaimed = 0
        for job_json in stale_jobs:
            await client.zrem(self.PROCESSING_KEY, job_json)
            await client.lpush(self.QUEUE_KEY, job_json)
            reclaimed += 1

        if reclaimed > 0:
            logger.info("stale_jobs_reclaimed", count=reclaimed)

        return reclaimed

    async def extend_visibility(self, job: BlogJob, additional_seconds: int = 60) -> None:
        client = await get_redis_client()
        job_json = json.dumps(job.__dict__)
        new_deadline = datetime.now(UTC).timestamp() + additional_seconds
        await client.zadd(self.PROCESSING_KEY, {job_json: new_deadline})
        logger.debug("visibility_extended", session_id=job.session_id, seconds=additional_seconds)


task_queue = TaskQueue()
