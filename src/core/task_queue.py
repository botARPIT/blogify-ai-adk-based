"""Enhanced task queue with job reclaim for crashed workers.

Features:
- Job visibility timeout (prevents lost jobs on crash)
- Automatic job reclaim for stale processing jobs
- Dead letter queue for failed jobs
"""

import asyncio
import hashlib
import json
import uuid
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable

import redis.asyncio as redis

from src.config.database_config import db_settings
from src.config.logging_config import get_logger

logger = get_logger(__name__)


class TaskStatus(str, Enum):
    """Task status values."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class QueueFullError(Exception):
    """Raised when queue depth exceeds maximum allowed."""
    pass


class TaskQueue:
    """
    Redis-backed async task queue with job reclaim support.
    
    Features:
    - Non-blocking task submission
    - Visibility timeout for crash recovery
    - Automatic stale job reclaim
    - Dead letter queue for permanent failures
    """

    
    QUEUE_NAME = "blogify:tasks"
    PROCESSING_SET = "blogify:processing"
    TASK_PREFIX = "blogify:task:"
    DEAD_LETTER = "blogify:deadletter"
    RESULT_TTL = 86400  # 24 hours
    VISIBILITY_TIMEOUT = 300  # 5 minutes - job reclaim if not completed
    MAX_QUEUE_DEPTH = 1000  # Maximum pending jobs - backpressure control
    
    def __init__(self, redis_url: str | None = None):
        self.redis_url = redis_url or db_settings.redis_url
        self._client: redis.Redis | None = None
        self._reclaim_task: asyncio.Task | None = None
    
    async def _get_client(self) -> redis.Redis:
        """Get or create Redis client."""
        if self._client is None:
            self._client = await redis.from_url(
                self.redis_url,
                decode_responses=True,
                socket_timeout=5.0,  # Fast-fail on Redis issues
                socket_connect_timeout=2.0,
            )
        return self._client
    
    async def enqueue(
        self,
        task_type: str,
        payload: dict,
        task_id: str | None = None,
        priority: int = 0,
    ) -> str:
        """
        Enqueue a new task with depth check.
        
        Args:
            task_type: Type of task (e.g., "blog_generation")
            payload: Task input data
            task_id: Optional task ID
            priority: Task priority (higher = more urgent)
            
        Returns:
            Task ID
            
        Raises:
            QueueFullError: If queue depth exceeds MAX_QUEUE_DEPTH
        """
        client = await self._get_client()
        
        # BACKPRESSURE: Check queue depth before enqueue
        current_depth = await client.llen(self.QUEUE_NAME)
        if current_depth >= self.MAX_QUEUE_DEPTH:
            logger.warning(
                "queue_depth_exceeded",
                current=current_depth,
                max=self.MAX_QUEUE_DEPTH,
            )
            raise QueueFullError(
                f"Queue depth {current_depth} exceeds maximum {self.MAX_QUEUE_DEPTH}"
            )
        
        if task_id is None:
            task_id = str(uuid.uuid4())
        
        task = {
            "id": task_id,
            "type": task_type,
            "payload": payload,
            "status": TaskStatus.PENDING.value,
            "priority": priority,
            "retries": 0,
            "max_retries": 3,
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
        }
        
        # Store task data
        task_key = f"{self.TASK_PREFIX}{task_id}"
        await client.set(task_key, json.dumps(task), ex=self.RESULT_TTL)
        
        # Add to queue
        await client.lpush(self.QUEUE_NAME, task_id)
        
        logger.info("task_enqueued", task_id=task_id, type=task_type, queue_depth=current_depth + 1)
        
        return task_id
    
    async def get_task_status(self, task_id: str) -> dict | None:
        """Get task status and result."""
        client = await self._get_client()
        
        task_key = f"{self.TASK_PREFIX}{task_id}"
        data = await client.get(task_key)
        
        if data is None:
            return None
        
        return json.loads(data)
    
    async def update_task(
        self,
        task_id: str,
        status: TaskStatus | None = None,
        result: dict | None = None,
        error: str | None = None,
        progress: int | None = None,
    ) -> None:
        """Update task status and data."""
        client = await self._get_client()
        
        task_key = f"{self.TASK_PREFIX}{task_id}"
        data = await client.get(task_key)
        
        if data is None:
            return
        
        task = json.loads(data)
        
        if status is not None:
            task["status"] = status.value
        
        if result is not None:
            task["result"] = result
        
        if error is not None:
            task["error"] = error
        
        if progress is not None:
            task["progress"] = progress
        
        task["updated_at"] = datetime.utcnow().isoformat()
        
        if status == TaskStatus.COMPLETED:
            task["completed_at"] = datetime.utcnow().isoformat()
            # Remove from processing set
            await client.zrem(self.PROCESSING_SET, task_id)
        
        if status == TaskStatus.FAILED:
            # Remove from processing set
            await client.zrem(self.PROCESSING_SET, task_id)
        
        await client.set(task_key, json.dumps(task), ex=self.RESULT_TTL)
        
        logger.debug("task_updated", task_id=task_id, status=status)
    
    async def dequeue(self, timeout: int = 5) -> dict | None:
        """
        Dequeue the next task with visibility timeout.
        
        Args:
            timeout: Wait timeout in seconds
            
        Returns:
            Task data or None if timeout
        """
        client = await self._get_client()
        
        # Blocking pop
        result = await client.brpop(self.QUEUE_NAME, timeout=timeout)
        
        if result is None:
            return None
        
        _, task_id = result
        
        task_key = f"{self.TASK_PREFIX}{task_id}"
        data = await client.get(task_key)
        
        if data is None:
            return None
        
        task = json.loads(data)
        task["status"] = TaskStatus.PROCESSING.value
        task["started_at"] = datetime.utcnow().isoformat()
        task["updated_at"] = datetime.utcnow().isoformat()
        
        # Add to processing set with visibility timeout score
        visibility_deadline = datetime.utcnow().timestamp() + self.VISIBILITY_TIMEOUT
        await client.zadd(self.PROCESSING_SET, {task_id: visibility_deadline})
        
        await client.set(task_key, json.dumps(task), ex=self.RESULT_TTL)
        
        logger.info("task_dequeued", task_id=task_id)
        
        return task
    
    async def extend_visibility(self, task_id: str, seconds: int = 300) -> None:
        """Extend the visibility timeout for a processing task."""
        client = await self._get_client()
        
        new_deadline = datetime.utcnow().timestamp() + seconds
        await client.zadd(self.PROCESSING_SET, {task_id: new_deadline})
        
        logger.debug("visibility_extended", task_id=task_id, seconds=seconds)
    
    async def requeue(self, task_id: str) -> None:
        """Requeue a failed task for retry."""
        client = await self._get_client()
        
        task_key = f"{self.TASK_PREFIX}{task_id}"
        data = await client.get(task_key)
        
        if data is None:
            return
        
        task = json.loads(data)
        task["retries"] = task.get("retries", 0) + 1
        task["status"] = TaskStatus.PENDING.value
        task["updated_at"] = datetime.utcnow().isoformat()
        task.pop("started_at", None)
        
        # Remove from processing set
        await client.zrem(self.PROCESSING_SET, task_id)
        
        await client.set(task_key, json.dumps(task), ex=self.RESULT_TTL)
        await client.lpush(self.QUEUE_NAME, task_id)
        
        logger.info("task_requeued", task_id=task_id, retries=task["retries"])
    
    async def reclaim_stale_jobs(self) -> int:
        """
        Reclaim jobs from crashed workers.
        
        Checks processing set for jobs past their visibility deadline
        and requeues them.
        
        Returns:
            Number of jobs reclaimed
        """
        client = await self._get_client()
        
        now = datetime.utcnow().timestamp()
        
        # Get all jobs past their deadline
        stale_jobs = await client.zrangebyscore(
            self.PROCESSING_SET,
            "-inf",
            now,
        )
        
        reclaimed = 0
        for task_id in stale_jobs:
            task_key = f"{self.TASK_PREFIX}{task_id}"
            data = await client.get(task_key)
            
            if data is None:
                # Task expired, just remove from set
                await client.zrem(self.PROCESSING_SET, task_id)
                continue
            
            task = json.loads(data)
            retries = task.get("retries", 0)
            max_retries = task.get("max_retries", 3)
            
            if retries >= max_retries:
                # Move to dead letter queue
                await client.lpush(self.DEAD_LETTER, task_id)
                await client.zrem(self.PROCESSING_SET, task_id)
                task["status"] = TaskStatus.FAILED.value
                task["error"] = "Max retries exceeded (job reclaim)"
                await client.set(task_key, json.dumps(task), ex=self.RESULT_TTL)
                logger.warning("job_moved_to_deadletter", task_id=task_id)
            else:
                # Requeue for retry
                await self.requeue(task_id)
                reclaimed += 1
                logger.info("job_reclaimed", task_id=task_id, retries=retries + 1)
        
        return reclaimed
    
    async def start_reclaim_loop(self, interval: int = 60):
        """Start background job reclaim loop."""
        
        async def reclaim_loop():
            while True:
                try:
                    reclaimed = await self.reclaim_stale_jobs()
                    if reclaimed > 0:
                        logger.info("reclaim_cycle_complete", reclaimed=reclaimed)
                except Exception as e:
                    logger.error("reclaim_error", error=str(e))
                
                await asyncio.sleep(interval)
        
        self._reclaim_task = asyncio.create_task(reclaim_loop())
        logger.info("reclaim_loop_started", interval=interval)
    
    async def stop_reclaim_loop(self):
        """Stop the background reclaim loop."""
        if self._reclaim_task:
            self._reclaim_task.cancel()
            try:
                await self._reclaim_task
            except asyncio.CancelledError:
                pass
            self._reclaim_task = None
            logger.info("reclaim_loop_stopped")
    
    async def get_queue_stats(self) -> dict:
        """Get queue statistics."""
        client = await self._get_client()
        
        pending = await client.llen(self.QUEUE_NAME)
        processing = await client.zcard(self.PROCESSING_SET)
        dead_letter = await client.llen(self.DEAD_LETTER)
        
        return {
            "pending": pending,
            "processing": processing,
            "dead_letter": dead_letter,
        }
    
    async def close(self):
        """Close connections and stop background tasks."""
        await self.stop_reclaim_loop()
        if self._client:
            await self._client.close()
            self._client = None


# Blog generation specific helpers
async def enqueue_blog_generation(
    user_id: str,
    topic: str,
    audience: str | None,
    session_id: str | None = None,
    blog_id: int | None = None,
) -> str:
    """
    Enqueue a blog generation task.
    
    Returns task_id for status polling.
    """
    queue = TaskQueue()
    
    task_id = await queue.enqueue(
        task_type="blog_generation",
        payload={
            "user_id": user_id,
            "topic": topic,
            "audience": audience or "general readers",
            "session_id": session_id or str(uuid.uuid4()),
            "blog_id": blog_id,
            "stage": "intent",  # Start at intent stage
        },
    )
    
    return task_id


async def get_generation_status(task_id: str) -> dict | None:
    """Get blog generation task status."""
    queue = TaskQueue()
    return await queue.get_task_status(task_id)


# Global instance
task_queue = TaskQueue()
