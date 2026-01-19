"""Async task queue for long-running blog generation.

Uses Redis-based task queue for non-blocking blog generation.
"""

import asyncio
import json
import uuid
from datetime import datetime
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


class TaskQueue:
    """
    Redis-backed async task queue for blog generation.
    
    Features:
    - Non-blocking task submission
    - Real-time status polling
    - Automatic retry with backoff
    - Task result storage
    - Worker-based processing
    """
    
    QUEUE_NAME = "blogify:tasks"
    TASK_PREFIX = "blogify:task:"
    RESULT_TTL = 86400  # 24 hours
    
    def __init__(self, redis_url: str | None = None):
        self.redis_url = redis_url or db_settings.redis_url
        self._client: redis.Redis | None = None
        self._is_running = False
    
    async def _get_client(self) -> redis.Redis:
        """Get or create Redis client."""
        if self._client is None:
            self._client = await redis.from_url(
                self.redis_url,
                decode_responses=True,
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
        Enqueue a new task.
        
        Args:
            task_type: Type of task (e.g., "blog_generation")
            payload: Task input data
            task_id: Optional task ID
            priority: Task priority (higher = more urgent)
            
        Returns:
            Task ID
        """
        client = await self._get_client()
        
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
        
        logger.info("task_enqueued", task_id=task_id, type=task_type)
        
        return task_id
    
    async def get_task_status(self, task_id: str) -> dict | None:
        """
        Get task status and result.
        
        Args:
            task_id: Task ID
            
        Returns:
            Task data or None if not found
        """
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
        """
        Update task status and data.
        
        Args:
            task_id: Task ID
            status: New status
            result: Task result (on completion)
            error: Error message (on failure)
            progress: Progress percentage (0-100)
        """
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
        
        await client.set(task_key, json.dumps(task), ex=self.RESULT_TTL)
        
        logger.debug("task_updated", task_id=task_id, status=status)
    
    async def dequeue(self, timeout: int = 5) -> dict | None:
        """
        Dequeue the next task (blocking).
        
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
        
        await client.set(task_key, json.dumps(task), ex=self.RESULT_TTL)
        
        logger.info("task_dequeued", task_id=task_id)
        
        return task
    
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
        
        await client.set(task_key, json.dumps(task), ex=self.RESULT_TTL)
        await client.lpush(self.QUEUE_NAME, task_id)
        
        logger.info("task_requeued", task_id=task_id, retries=task["retries"])
    
    async def process_task(
        self,
        task: dict,
        handler: Callable[[dict], Any],
    ) -> None:
        """
        Process a task with the given handler.
        
        Args:
            task: Task data
            handler: Async function to process task
        """
        task_id = task["id"]
        
        try:
            result = await handler(task["payload"])
            
            await self.update_task(
                task_id,
                status=TaskStatus.COMPLETED,
                result=result,
            )
            
            logger.info("task_completed", task_id=task_id)
            
        except Exception as e:
            logger.error("task_failed", task_id=task_id, error=str(e))
            
            task_data = await self.get_task_status(task_id)
            retries = task_data.get("retries", 0) if task_data else 0
            max_retries = task_data.get("max_retries", 3) if task_data else 3
            
            if retries < max_retries:
                await self.requeue(task_id)
            else:
                await self.update_task(
                    task_id,
                    status=TaskStatus.FAILED,
                    error=str(e),
                )


# Blog generation specific helper
async def enqueue_blog_generation(
    user_id: str,
    topic: str,
    audience: str | None,
    session_id: str | None = None,
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
        },
    )
    
    return task_id


async def get_generation_status(task_id: str) -> dict | None:
    """Get blog generation task status."""
    queue = TaskQueue()
    return await queue.get_task_status(task_id)


# Global instance
task_queue = TaskQueue()
