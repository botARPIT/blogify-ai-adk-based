"""BlogService — owns blog session lifecycle from API side."""

import uuid
from typing import Optional

import redis.asyncio as redis
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.redis_pool import get_redis_client
from src.core.task_queue import BlogJob, TaskQueue
from src.models.orm_models import BlogSession, BlogSessionStatus
from src.models.repositories.blog_session_repository import BlogSessionRepository
from src.services.budget_service import BudgetService


class BlogService:
    MAX_ACTIVE_SESSIONS_PER_USER = 1

    def __init__(
        self,
        session_repo: BlogSessionRepository,
        budget_service: BudgetService,
        task_queue: TaskQueue,
        redis_client,
    ) -> None:
        self._session_repo = session_repo
        self._budget_service = budget_service
        self._task_queue = task_queue
        self._redis = redis_client

    async def create_generation(
        self,
        *,
        user_id: int,
        topic: str,
        audience: str,
        tone: str,
        idempotency_key: Optional[str] = None,
    ) -> BlogSession:
        if idempotency_key:
            existing = await self._session_repo.get_by_idempotency_key(
                user_id, idempotency_key
            )
            if existing:
                return existing

        active_count = await self._session_repo.count_active_for_user(user_id)
        if active_count >= self.MAX_ACTIVE_SESSIONS_PER_USER:
            raise ValueError("User already has an active generation")

        adk_session_id = str(uuid.uuid4())
        session = await self._session_repo.create(
            user_id=user_id,
            topic=topic,
            audience=audience,
            tone=tone,
            adk_session_id=adk_session_id,
            idempotency_key=idempotency_key,
        )

        lock_acquired = await self._redis.set(
            f"budget_lock:{user_id}", "1", nx=True, ex=10
        )
        if not lock_acquired:
            raise ValueError("Rate limit exceeded, try again later")

        try:
            await self._budget_service.check_and_reserve(user_id, session.id)
        finally:
            await self._redis.delete(f"budget_lock:{user_id}")

        job = BlogJob(
            session_id=session.id,
            user_id=user_id,
            adk_session_id=adk_session_id,
            topic=topic,
            audience=audience,
            tone=tone,
            phase="start",
        )
        await self._task_queue.enqueue(job)

        return session

    async def get_user_sessions(self, user_id: int) -> list[BlogSession]:
        return await self._session_repo.get_for_user(user_id)

    async def get_session(self, user_id: int, session_id: int) -> BlogSession:
        session = await self._session_repo.get_by_id(session_id)
        if not session:
            raise ValueError("Session not found")
        if session.user_id != user_id:
            raise ValueError("Access denied")
        return session

    async def submit_outline_review(
        self,
        *,
        user_id: int,
        session_id: int,
        approved_outline: dict,
        feedback_text: Optional[str] = None,
    ) -> BlogSession:
        session = await self.get_session(user_id, session_id)
        if session.status != BlogSessionStatus.AWAITING_OUTLINE_REVIEW.value:
            raise ValueError("Session not awaiting outline review")

        session.outline_data = approved_outline
        session.status = BlogSessionStatus.QUEUED.value
        await self._session_repo.session.flush()

        job = BlogJob(
            session_id=session.id,
            user_id=user_id,
            adk_session_id=session.adk_session_id,
            topic=session.topic,
            audience=session.audience,
            tone=session.tone,
            phase="resume_outline",
            invocation_id=session.invocation_id,
            confirmation_request_id=session.confirmation_request_id,
            approved_outline=approved_outline,
            feedback_text=feedback_text,
        )
        await self._task_queue.enqueue(job)

        return session

    async def submit_final_review(
        self,
        *,
        user_id: int,
        session_id: int,
        approved: bool,
        feedback_text: Optional[str] = None,
    ) -> BlogSession:
        from datetime import datetime, timezone

        session = await self.get_session(user_id, session_id)
        if session.status != BlogSessionStatus.AWAITING_FINAL_REVIEW.value:
            raise ValueError("Session not awaiting final review")

        if approved:
            session.status = BlogSessionStatus.COMPLETED.value
            session.completed_at = datetime.now(timezone.utc)
        else:
            session.status = BlogSessionStatus.FAILED.value
            session.failure_reason = feedback_text or "Rejected by user"

        await self._session_repo.session.flush()
        return session

    async def get_budget(self, user_id: int) -> dict:
        return await self._budget_service.get_balance_snapshot(user_id)