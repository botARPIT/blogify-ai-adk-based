"""Blog pipeline executor for worker processes.

Replaces the per-stage executor with a single ``run_pipeline()`` call
that uses ADK-native orchestration.  Cost tracking and blog record
updates are handled here (pipeline_v2 is pure orchestration).
"""

from __future__ import annotations

from typing import Any

from src.agents.pipeline_v2 import (
    CostInfo,
    PipelineResult,
    run_pipeline,
    resume_pipeline,
)
from src.config.budget_config import get_model_cost
from src.config.logging_config import get_logger
from src.models.orm_models import BlogSessionStatus, EndUser
from src.models.repository import db_repository
from src.models.repositories.auth_user_repository import AuthUserRepository
from src.models.repositories.agent_run_repository import AgentRunRepository
from src.models.repositories.blog_session_repository import BlogSessionRepository
from src.models.repositories.blog_version_repository import BlogVersionRepository
from src.models.repositories.budget_repository import BudgetRepository
from src.models.repositories.human_review_repository import HumanReviewRepository
from src.models.repositories.notification_repository import NotificationRepository
from src.monitoring.tracing import trace_span
from src.services.budget_service import BudgetService
from src.services.notification_service import NotificationService
from src.services.revision_service import RevisionService

logger = get_logger(__name__)


class StageExecutor:
    """Execute the full blog generation pipeline and persist results.

    The ADK SequentialAgent handles stage-by-stage orchestration
    internally.  This class is responsible for:

    1. Calling ``run_pipeline()``
    2. Persisting results to the database
    3. Recording cost entries
    """

    async def execute_full_pipeline(
        self,
        blog_id: int | None,
        session_id: str,
        topic: str,
        audience: str = "general readers",
        user_id: str = "anonymous",
        canonical_session_id: int | None = None,
    ) -> PipelineResult:
        """Run the entire blog pipeline and persist results.

        Parameters
        ----------
        blog_id:
            Database blog ID for updates.
        session_id:
            External session ID.
        topic:
            Blog topic.
        audience:
            Target audience.
        user_id:
            Real user id — propagated into the ADK session.

        Returns
        -------
        PipelineResult with all stage outputs and cost info.
        """
        with trace_span("stage_executor.full_pipeline", {"blog_id": blog_id, "session_id": session_id}):
            logger.info(
                "pipeline_execution_start",
                blog_id=blog_id,
                session_id=session_id,
                topic=topic[:80],
            )

            if canonical_session_id is not None:
                await self._mark_canonical_processing(canonical_session_id, current_stage="intent")

            # ── Run the pipeline ────────────────────────────────────
            result = await run_pipeline(
                topic=topic,
                audience=audience,
                user_id=user_id,
                session_id=session_id,
            )

            # ── Persist results ─────────────────────────────────────
            if result.error:
                if blog_id is not None:
                    await db_repository.update_blog(
                        session_id=session_id,
                        status="failed",
                    )
                logger.error(
                    "pipeline_execution_failed",
                    blog_id=blog_id,
                    session_id=session_id,
                    error=result.error,
                )
                return result

            if canonical_session_id is not None and result.paused_for_confirmation:
                await self._store_outline_review_gate(
                    canonical_session_id=canonical_session_id,
                    result=result,
                )
                logger.info(
                    "pipeline_paused_for_outline_review",
                    session_id=session_id,
                    canonical_session_id=canonical_session_id,
                    invocation_id=result.invocation_id,
                )
                return result

            # Update blog with final content
            title = ""
            if result.outline and isinstance(result.outline, dict):
                title = result.outline.get("title", "")

            word_count = len(result.final_content.split()) if result.final_content else 0
            sources_count = 0
            if result.research and isinstance(result.research, dict):
                sources_count = result.research.get("total_sources", 0)

            total_tokens = sum(c.total_tokens for c in result.costs)
            total_cost_usd = sum(
                get_model_cost(c.model, c.total_tokens)
                for c in result.costs
                if c.model
            )

            if blog_id is not None:
                await db_repository.update_blog(
                    session_id=session_id,
                    title=title,
                    content=result.final_content,
                    word_count=word_count,
                    sources_count=sources_count,
                    status="completed",
                    total_cost_usd=total_cost_usd,
                    total_tokens=total_tokens,
                )

            # ── Record cost entries ─────────────────────────────────
            if blog_id is not None:
                await self._record_costs(
                    user_id=user_id,
                    session_id=session_id,
                    blog_id=blog_id,
                    costs=result.costs,
                )

            if canonical_session_id is not None:
                await self._finalize_canonical_success(
                    canonical_session_id=canonical_session_id,
                    result=result,
                    title=title,
                    word_count=word_count,
                    sources_count=sources_count,
                )

            # ── Persist per-stage data for audit trail ──────────────
            stage_data = {
                "intent": result.intent_result,
                "outline": result.outline,
                "research": result.research,
                "draft": result.draft[:500] if result.draft else None,
                "editor_review": result.editor_review,
            }
            if blog_id is not None:
                await db_repository.update_blog_stage(
                    session_id=session_id,
                    stage="completed",
                    stage_data=stage_data,
                )

            logger.info(
                "pipeline_execution_complete",
                blog_id=blog_id,
                session_id=session_id,
                title=title[:50],
                word_count=word_count,
                total_tokens=total_tokens,
                total_cost_usd=round(total_cost_usd, 6),
            )

            return result

    async def execute_resume_from_outline(
        self,
        *,
        session_id: str,
        topic: str,
        audience: str = "general readers",
        user_id: str = "anonymous",
        canonical_session_id: int,
        invocation_id: str,
        confirmation_request_id: str,
        approved_outline: dict[str, Any],
        feedback_text: str | None = None,
    ) -> PipelineResult:
        if not invocation_id or not confirmation_request_id or not approved_outline:
            result = PipelineResult(session_id=session_id)
            result.error = "Missing outline resume context"
            return result

        await self._mark_canonical_processing(canonical_session_id, current_stage="research")

        result = await resume_pipeline(
            topic=topic,
            audience=audience,
            user_id=user_id,
            session_id=session_id,
            invocation_id=invocation_id,
            confirmation_request_id=confirmation_request_id,
            approved_outline=approved_outline,
            feedback_text=feedback_text,
        )
        if result.error:
            logger.error(
                "resume_from_outline_failed",
                session_id=session_id,
                canonical_session_id=canonical_session_id,
                error=result.error,
            )
            return result

        title = ""
        if result.outline and isinstance(result.outline, dict):
            title = result.outline.get("title", "")

        word_count = len(result.final_content.split()) if result.final_content else 0
        sources_count = 0
        if result.research and isinstance(result.research, dict):
            sources_count = result.research.get("total_sources", 0)

        await self._finalize_canonical_success(
            canonical_session_id=canonical_session_id,
            result=result,
            title=title,
            word_count=word_count,
            sources_count=sources_count,
        )
        return result

    # -- legacy compat shim for blog_worker.py stage loop --------
    async def execute_stage(
        self,
        blog_id: int,
        stage: str,
        canonical_session_id: int | None = None,
    ) -> tuple[dict[str, Any], str]:
        """Legacy shim — runs the full pipeline in a single call.

        ``blog_worker.py`` still drives a stage loop; this shim
        translates a stage-loop call into a single full-pipeline call
        so the worker gets ``("completed", result)`` on the first
        invocation and never re-enters.
        """
        blog = await db_repository.get_blog(blog_id)
        if not blog:
            return {"error": f"Blog {blog_id} not found"}, "failed"

        result = await self.execute_full_pipeline(
            blog_id=blog_id,
            session_id=blog.session_id,
            topic=blog.topic,
            audience=blog.audience or "general readers",
            user_id=getattr(blog, "user_id", "anonymous"),
            canonical_session_id=canonical_session_id,
        )

        if result.error:
            return {"error": result.error}, "failed"

        return {
            "title": result.outline.get("title", "") if result.outline else "",
            "content": result.final_content,
        }, "completed"

    # -- cost recording ------------------------------------------

    async def _record_costs(
        self,
        user_id: str,
        session_id: str,
        blog_id: int,
        costs: list[CostInfo],
    ) -> None:
        """Write cost tracking records for each pipeline stage."""
        for cost in costs:
            if cost.total_tokens == 0:
                continue

            cost_usd = get_model_cost(
                cost.model, cost.total_tokens
            )

            try:
                await db_repository.create_cost_record(
                    user_id=user_id,
                    session_id=session_id,
                    agent_name=cost.stage,
                    model_name=cost.model,
                    prompt_tokens=cost.prompt_tokens,
                    completion_tokens=cost.completion_tokens,
                    total_tokens=cost.total_tokens,
                    cost_usd=cost_usd,
                    blog_id=blog_id,
                )
            except Exception as exc:
                logger.warning(
                    "cost_record_failed",
                    stage=cost.stage,
                    error=str(exc),
                )

    async def _record_canonical_stage_costs(
        self,
        *,
        canonical_session_id: int,
        costs: list[CostInfo],
    ) -> None:
        async with db_repository.async_session() as session:
            async with session.begin():
                session_repo = BlogSessionRepository(session)
                run_repo = AgentRunRepository(session)
                budget_repo = BudgetRepository(session)

                blog_session = await session_repo.get_by_id(canonical_session_id)
                if blog_session is None:
                    return

                budget_service = BudgetService(
                    budget_repo=budget_repo,
                    session_repo=session_repo,
                )

                for cost in costs:
                    if cost.total_tokens == 0:
                        continue
                    cost_usd = get_model_cost(cost.model, cost.total_tokens)
                    run = await run_repo.start(
                        blog_session_id=canonical_session_id,
                        stage_name=cost.stage,
                        agent_name=cost.stage,
                        model_name=cost.model or "unknown",
                    )
                    await run_repo.complete(
                        run_id=run.id,
                        prompt_tokens=cost.prompt_tokens,
                        completion_tokens=cost.completion_tokens,
                        cost_usd=cost_usd,
                        latency_ms=0,
                    )
                    await budget_service.commit_stage(
                        tenant_id=blog_session.tenant_id,
                        end_user_id=blog_session.end_user_id,
                        blog_session_id=canonical_session_id,
                        agent_run_id=run.id,
                        actual_tokens=cost.total_tokens,
                        actual_usd=cost_usd,
                    )

    async def _mark_canonical_processing(
        self,
        canonical_session_id: int,
        current_stage: str,
    ) -> None:
        async with db_repository.async_session() as session:
            async with session.begin():
                session_repo = BlogSessionRepository(session)
                await session_repo.update_status(
                    canonical_session_id,
                    status=BlogSessionStatus.PROCESSING,
                    current_stage=current_stage,
                )

    async def _store_outline_review_gate(
        self,
        *,
        canonical_session_id: int,
        result: PipelineResult,
    ) -> None:
        if not isinstance(result.outline, dict):
            return

        await self._record_canonical_stage_costs(
            canonical_session_id=canonical_session_id,
            costs=result.costs,
        )

        async with db_repository.async_session() as session:
            async with session.begin():
                session_repo = BlogSessionRepository(session)
                auth_user_repo = AuthUserRepository(session)
                notification_repo = NotificationRepository(session)
                await session_repo.update_outline(
                    canonical_session_id,
                    outline_data=result.outline,
                )
                await session_repo.update_status(
                    canonical_session_id,
                    status=BlogSessionStatus.AWAITING_OUTLINE_REVIEW,
                    current_stage="outline_review",
                )
                blog_session = await session_repo.get_by_id(canonical_session_id)
                if blog_session is not None:
                    end_user = await session.get(EndUser, blog_session.end_user_id)
                    notification_service = NotificationService(
                        auth_user_repo=auth_user_repo,
                        notification_repo=notification_repo,
                    )
                    await notification_service.create_for_end_user(
                        end_user=end_user,
                        type="outline_review_required",
                        title="Outline review needed",
                        message=f"Session {canonical_session_id} is waiting for your outline approval.",
                        session_id=canonical_session_id,
                        action_url=f"/sessions/{canonical_session_id}/outline-review",
                    )

        logger.info(
            "outline_review_required",
            canonical_session_id=canonical_session_id,
            session_id=result.session_id,
        )

    async def _finalize_canonical_success(
        self,
        canonical_session_id: int,
        result: PipelineResult,
        title: str,
        word_count: int,
        sources_count: int,
    ) -> None:
        async with db_repository.async_session() as session:
            async with session.begin():
                session_repo = BlogSessionRepository(session)
                version_repo = BlogVersionRepository(session)
                budget_repo = BudgetRepository(session)
                run_repo = AgentRunRepository(session)
                review_repo = HumanReviewRepository(session)
                auth_user_repo = AuthUserRepository(session)
                notification_repo = NotificationRepository(session)

                blog_session = await session_repo.get_by_id(canonical_session_id)
                if blog_session is None:
                    logger.warning("canonical_session_missing", session_id=canonical_session_id)
                    return

                budget_service = BudgetService(
                    budget_repo=budget_repo,
                    session_repo=session_repo,
                )
                revision_service = RevisionService(
                    session_repo=session_repo,
                    version_repo=version_repo,
                    review_repo=review_repo,
                    budget_repo=budget_repo,
                    auth_user_repo=auth_user_repo,
                    notification_repo=notification_repo,
                )

                for cost in result.costs:
                    if cost.total_tokens == 0:
                        continue

                    cost_usd = get_model_cost(
                        cost.model, cost.total_tokens
                    )
                    run = await run_repo.start(
                        blog_session_id=canonical_session_id,
                        stage_name=cost.stage,
                        agent_name=cost.stage,
                        model_name=cost.model or "unknown",
                    )
                    await run_repo.complete(
                        run_id=run.id,
                        prompt_tokens=cost.prompt_tokens,
                        completion_tokens=cost.completion_tokens,
                        cost_usd=cost_usd,
                        latency_ms=0,
                    )
                    await budget_service.commit_stage(
                        tenant_id=blog_session.tenant_id,
                        end_user_id=blog_session.end_user_id,
                        blog_session_id=canonical_session_id,
                        agent_run_id=run.id,
                        actual_tokens=cost.total_tokens,
                        actual_usd=cost_usd,
                    )

                await revision_service.record_editor_output(
                    blog_session_id=canonical_session_id,
                    content_markdown=result.final_content,
                    title=title or None,
                    word_count=word_count,
                    sources_count=sources_count,
                    editor_approved=bool(
                        isinstance(result.editor_review, dict)
                        and result.editor_review.get("approved")
                    ),
                )

                await budget_service.release(
                    tenant_id=blog_session.tenant_id,
                    end_user_id=blog_session.end_user_id,
                    blog_session_id=canonical_session_id,
                    reserved_usd=blog_session.budget_reserved_usd,
                    reserved_tokens=blog_session.budget_reserved_tokens,
                    already_spent_usd=blog_session.budget_spent_usd,
                    already_spent_tokens=blog_session.budget_spent_tokens,
                )
