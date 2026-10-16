"""BlogService — owns blog session lifecycle from API side."""

import uuid
from datetime import datetime, timezone

from src.config.api_config import DAILY_BLOG_GENERATION_LIMIT
from src.config.logging_config import get_logger
from src.core.task_queue import BlogJob, TaskQueue
from src.models.orm_models import (
    BlogJobPhase,
    BlogSession,
    BlogSessionStatus,
    FinalReviewAction,
    UserAction,
)
from src.models.repositories.blog_quota_repository import BlogQuotaRepository
from src.models.repositories.blog_review_event_repository import BlogReviewEventRepository
from src.models.repositories.blog_session_repository import BlogSessionRepository
from src.models.repositories.blog_version_repository import BlogVersionRepository
from src.models.repositories.workflow_outbox_repository import WorkflowOutboxRepository
from src.models.schemas import OutlineSchema
from src.services.budget_service import BudgetService
from src.services.exceptions import DailyBlogLimitExceededError, SessionTerminalError

logger = get_logger(__name__)


class BlogService:
    MAX_ACTIVE_SESSIONS_PER_USER = 1

    def __init__(
        self,
        session_repo: BlogSessionRepository,
        version_repo: BlogVersionRepository,
        budget_service: BudgetService,
        task_queue: TaskQueue,
        redis_client,
    ) -> None:
        print("DEBUG [blog_service.py:16] BlogService.__init__ called", flush=True)
        self._session_repo = session_repo
        self._version_repo = version_repo
        self._budget_service = budget_service
        self._task_queue = task_queue
        self._redis = redis_client
        self._outbox = WorkflowOutboxRepository(session_repo.session)
        self._review_events = BlogReviewEventRepository(session_repo.session)
        self._quota_repo = BlogQuotaRepository(session_repo.session)

    async def commit_and_dispatch(self, session_id: int) -> None:
        """Commit API state, then publish its event as a fast path to Redis.

        The reaper recovers failed publishes. Duplicate delivery is safe because
        workers claim an outbox event by ID in PostgreSQL.
        """
        db_session = self._session_repo.session
        event = await self._outbox.get_undispatched_for_aggregate(session_id)
        await db_session.commit()
        if event is None:
            return

        try:
            job_data = dict(event.payload["job"])
            job_data["outbox_event_id"] = event.id
            await self._task_queue.enqueue(BlogJob(**job_data))
        except Exception as exc:
            logger.warning(
                "outbox_fast_dispatch_failed",
                event_id=event.id,
                session_id=session_id,
                error=str(exc),
            )
            return

        try:
            await self._outbox.mark_dispatched(event.id)
            await db_session.commit()
        except Exception as exc:
            await db_session.rollback()
            logger.warning(
                "outbox_dispatch_marker_failed",
                event_id=event.id,
                session_id=session_id,
                error=str(exc),
            )

    async def create_generation(
        self,
        *,
        user_id: int,
        topic: str,
        audience: str,
        tone: str,
        idempotency_key: str | None = None,
    ) -> BlogSession:
        print(f"DEBUG [blog_service.py:28] BlogService.create_generation called: user_id={user_id}, topic={topic}, audience={audience}, tone={tone}, idempotency_key={idempotency_key}", flush=True)
        if idempotency_key:
            existing = await self._session_repo.get_by_idempotency_key(user_id, idempotency_key)
            if existing:
                terminal = {status.value for status in BlogSessionStatus.terminal_states()}
                if existing.status in terminal:
                    raise SessionTerminalError(
                        f"Session {existing.id} is in terminal state '{existing.status}'. "
                        "Generate a new Idempotency-Key to start a fresh request."
                    )
                # Non-terminal — return existing for status-polling
                return existing

        active_count = await self._session_repo.count_active_for_user(user_id)
        if active_count >= self.MAX_ACTIVE_SESSIONS_PER_USER:
            raise ValueError("User already has an active generation")

        # This atomic upsert shares the transaction with session and outbox
        # creation. The route commits them together after budget reservation;
        # rejected requests therefore do not consume a daily slot.
        quota_consumed = await self._quota_repo.consume_daily_slot(
            user_id=user_id,
            daily_limit=DAILY_BLOG_GENERATION_LIMIT,
            usage_date=datetime.now(timezone.utc).date(),
        )
        if not quota_consumed:
            raise DailyBlogLimitExceededError(DAILY_BLOG_GENERATION_LIMIT)

        adk_session_id = str(uuid.uuid4())
        session = await self._session_repo.create(
            user_id=user_id,
            topic=topic,
            audience=audience,
            tone=tone,
            adk_session_id=adk_session_id,
            idempotency_key=idempotency_key,
        )
        await self._version_repo.create_initial_version(
            blog_session=session,
            created_from=BlogJobPhase.FRESH_GENERATION.value,
            state_snapshot={
                "topic": topic,
                "audience": audience,
                "intent_result": {},
                "blog_outline": {},
                "approved_outline": {},
                "outline_feedback": "",
                "outline_review_result": {},
                "research_data": {},
                "blog_draft": "",
                "editor_review": {},
            },
        )

        lock_acquired = await self._redis.set(f"budget_lock:{user_id}", "1", nx=True, ex=10)
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
            phase=BlogJobPhase.FRESH_GENERATION.value,
        )
        await self._outbox.enqueue(
            event_type="blog.generate",
            aggregate_id=session.id,
            payload={"job": job.__dict__},
        )

        return session

    async def get_user_sessions(self, user_id: int) -> list[BlogSession]:
        print(f"DEBUG [blog_service.py:89] BlogService.get_user_sessions called: user_id={user_id}", flush=True)
        return await self._session_repo.get_for_user(user_id)

    async def get_session(self, user_id: int, session_id: int) -> BlogSession:
        print(f"DEBUG [blog_service.py:92] BlogService.get_session called: user_id={user_id}, session_id={session_id}", flush=True)
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
        feedback_text: str | None = None,
        action: str = "approve",
    ) -> BlogSession:
        print(f"DEBUG [blog_service.py:100] BlogService.submit_outline_review called: user_id={user_id}, session_id={session_id}, approved_outline={approved_outline}, feedback_text={feedback_text}", flush=True)
        session = await self._session_repo.get_by_id_for_update(session_id)
        if not session:
            raise ValueError("Session not found")
        if session.user_id != user_id:
            raise ValueError("Access denied")
        if session.status != BlogSessionStatus.AWAITING_OUTLINE_REVIEW.value:
            raise ValueError("Session not awaiting outline review")

        approved_outline = OutlineSchema.model_validate(approved_outline).model_dump()

        active_version = await self._version_repo.get_active_for_session(session.id)
        if active_version is None:
            raise ValueError("Active blog version not found")

        await self._review_events.create(
            blog_session_id=session.id,
            blog_version_id=active_version.id,
            reviewer_user_id=user_id,
            action=f"outline_{action}",
            feedback_text=feedback_text,
        )

        snapshot = dict(active_version.state_snapshot or {})
        snapshot["blog_outline"] = approved_outline
        snapshot["approved_outline"] = approved_outline
        snapshot["outline_feedback"] = feedback_text or ""

        await self._version_repo.update_version_state(
            active_version.id,
            status=BlogSessionStatus.QUEUED.value,
            job_phase=BlogJobPhase.RESEARCH_PHASE.value,
            outline_data=approved_outline,
            approved_outline=approved_outline,
            feedback_text=feedback_text or "",
            state_snapshot=snapshot,
        )

        session.outline_data = approved_outline
        session.status = BlogSessionStatus.QUEUED.value
        session.job_phase = BlogJobPhase.RESEARCH_PHASE.value
        session.updated_at = datetime.now(timezone.utc)
        await self._session_repo.session.flush()

        job = BlogJob(
            session_id=session.id,
            user_id=user_id,
            adk_session_id=session.adk_session_id,
            topic=session.topic,
            audience=session.audience,
            tone=session.tone,
            phase=BlogJobPhase.RESEARCH_PHASE.value,
        )
        await self._outbox.enqueue(
            event_type="blog.continue_after_outline_review",
            aggregate_id=session.id,
            payload={"job": job.__dict__},
        )

        return session

    async def submit_final_review(
        self,
        *,
        user_id: int,
        session_id: int,
        action: str,
        feedback_text: str | None = None,
    ) -> BlogSession:
        print(f"DEBUG [blog_service.py:133] BlogService.submit_final_review called: user_id={user_id}, session_id={session_id}, action={action}, feedback_text={feedback_text}", flush=True)
        session = await self._session_repo.get_by_id_for_update(session_id)
        if not session:
            raise ValueError("Session not found")
        if session.user_id != user_id:
            raise ValueError("Access denied")
        if session.status != BlogSessionStatus.AWAITING_FINAL_REVIEW.value:
            raise ValueError("Session not awaiting final review")

        active_version = await self._version_repo.get_active_for_session(session.id)
        review_action = FinalReviewAction(action)

        await self._review_events.create(
            blog_session_id=session.id,
            blog_version_id=active_version.id if active_version else None,
            reviewer_user_id=user_id,
            action=f"final_{review_action.value}",
            feedback_text=feedback_text,
        )

        if review_action == FinalReviewAction.APPROVED:
            session.status = BlogSessionStatus.COMPLETED.value
            session.completed_at = datetime.now(timezone.utc)
            session.updated_at = datetime.now(timezone.utc)
            if active_version:
                await self._version_repo.update_version_state(
                    active_version.id,
                    status=session.status,
                    feedback_text=feedback_text or active_version.feedback_text,
                    user_action=UserAction.APPROVED.value,
                    completed=True,
                )
        elif review_action == FinalReviewAction.REVISION_REQUESTED:
            session.status = BlogSessionStatus.QUEUED.value
            session.job_phase = BlogJobPhase.REVISION.value
            session.current_stage = "revision_requested"
            session.failure_reason = None
            session.updated_at = datetime.now(timezone.utc)

            if active_version:
                snapshot = dict(active_version.state_snapshot or {})
                snapshot["outline_feedback"] = feedback_text or ""
                await self._version_repo.update_version_state(
                    active_version.id,
                    status=BlogSessionStatus.QUEUED.value,
                    job_phase=BlogJobPhase.REVISION.value,
                    feedback_text=feedback_text or active_version.feedback_text,
                    user_action=UserAction.REVISION_REQUESTED.value,
                    state_snapshot=snapshot,
                )

            job = BlogJob(
                session_id=session.id,
                user_id=user_id,
                adk_session_id=session.adk_session_id,
                topic=session.topic,
                audience=session.audience,
                tone=session.tone,
                phase=BlogJobPhase.REVISION.value,
                feedback_text=feedback_text,
            )
            await self._outbox.enqueue(
                event_type="blog.revise",
                aggregate_id=session.id,
                payload={"job": job.__dict__},
            )
        else:
            session.status = BlogSessionStatus.REJECTED.value
            session.current_stage = "rejected"
            session.job_phase = None
            session.failure_reason = "Rejected by user"
            session.updated_at = datetime.now(timezone.utc)
            if active_version:
                await self._version_repo.update_version_state(
                    active_version.id,
                    status=BlogSessionStatus.REJECTED.value,
                    feedback_text=active_version.feedback_text,
                    user_action=UserAction.REJECTED.value,
                )

        await self._session_repo.session.flush()
        return session

    async def get_budget(self, user_id: int) -> dict:
        print(f"DEBUG [blog_service.py:156] BlogService.get_budget called: user_id={user_id}", flush=True)
        return await self._budget_service.get_balance_snapshot(user_id)
