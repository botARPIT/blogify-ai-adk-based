"""Redis task queue with atomic dequeue using Lua script."""

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone

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
    enqueued_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


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

        deadline = datetime.now(timezone.utc).timestamp() + self.VISIBILITY_TIMEOUT_SECONDS

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
        now = datetime.now(timezone.utc).timestamp()

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

    async def get_tracked_session_ids(self) -> set[int]:
        """Return session IDs currently present in the queue or processing set."""
        client = await get_redis_client()
        queued_jobs = await client.lrange(self.QUEUE_KEY, 0, -1)
        processing_jobs = await client.zrange(self.PROCESSING_KEY, 0, -1)

        session_ids: set[int] = set()
        for raw_job in [*queued_jobs, *processing_jobs]:
            payload = self._decode_job_payload(raw_job)
            session_id = payload.get("session_id")
            if isinstance(session_id, int):
                session_ids.add(session_id)

        return session_ids

    async def get_stale_processing_entries(self) -> list[str]:
        client = await get_redis_client()
        now = datetime.now(timezone.utc).timestamp()
        return list(
            await client.zrangebyscore(
                self.PROCESSING_KEY,
                "-inf",
                now,
            )
        )

    async def remove_processing_entry(self, job_json: str) -> bool:
        client = await get_redis_client()
        removed = await client.zrem(self.PROCESSING_KEY, job_json)
        return bool(removed)

    async def requeue_processing_entry(self, job_json: str) -> bool:
        client = await get_redis_client()
        removed = await client.zrem(self.PROCESSING_KEY, job_json)
        if not removed:
            return False

        await client.lpush(self.QUEUE_KEY, job_json)
        return True

    async def extend_visibility(self, job: BlogJob, additional_seconds: int = 60) -> None:
        client = await get_redis_client()
        job_json = json.dumps(job.__dict__)
        new_deadline = datetime.now(timezone.utc).timestamp() + additional_seconds
        await client.zadd(self.PROCESSING_KEY, {job_json: new_deadline})
        logger.debug("visibility_extended", session_id=job.session_id, seconds=additional_seconds)

    def _decode_job_payload(self, raw_job: str | bytes) -> dict:
        if isinstance(raw_job, bytes):
            raw_job = raw_job.decode("utf-8")

        try:
            payload = json.loads(raw_job)
        except Exception:
            return {}

        return payload if isinstance(payload, dict) else {}


task_queue = TaskQueue()
