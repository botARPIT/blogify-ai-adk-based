"""PipelineExecutor — bridges worker to ADK pipeline."""

import json
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.pipeline import (
    CostInfo,
    PipelineResult,
    resume_pipeline,
    run_pipeline,
    run_pipeline_from_phase,
)
from src.config.agent_config import agent_delay
from src.config.budget_config import get_model_cost
from src.core.task_queue import BlogJob
from src.models.orm_models import AgentRunStatus, BlogJobPhase, BlogSessionStatus
from src.models.repositories.agent_run_repository import AgentRunRepository
from src.models.repositories.blog_session_repository import BlogSessionRepository
from src.models.repositories.blog_version_repository import BlogVersionRepository
from src.models.repositories.budget_account_repository import BudgetAccountRepository
from src.models.repositories.budget_repository import BudgetRepository
from src.models.repositories.research_sources_repository import ResearchSourcesRepository
from src.models.repositories.session_reservation_repository import SessionReservationRepository
from src.monitoring.tracing import trace_span
from src.services.budget_service import BudgetService


class PipelineExecutor:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._session_repo = BlogSessionRepository(session)
        self._version_repo = BlogVersionRepository(session)
        self._run_repo = AgentRunRepository(session)
        self._budget_repo = BudgetRepository(session)
        self._account_repo = BudgetAccountRepository(session)
        self._reservation_repo = SessionReservationRepository(session)
        self._budget_service = BudgetService(
            self._budget_repo,
            self._session_repo,
            self._account_repo,
            self._reservation_repo,
        )
        self._sources_repo = ResearchSourcesRepository(session)

    async def execute(self, job: BlogJob) -> None:
        with trace_span("pipeline_executor.execute", {
            "job_phase": job.phase,
            "adk_session_id": str(job.adk_session_id),
            "user_id": str(job.user_id),
        }) as span:
            try:
                if job.phase == BlogJobPhase.FRESH_GENERATION.value:
                    await self._execute_fresh_generation(job)
                elif job.phase == BlogJobPhase.RESUME_OUTLINE.value:
                    await self._execute_resume_outline(job)
                elif job.phase == BlogJobPhase.RESEARCH_PHASE.value:
                    await self._execute_research_phase(job)
                elif job.phase == BlogJobPhase.REVISION.value:
                    await self._execute_revision(job)
                else:
                    raise ValueError(f"Unknown job phase: {job.phase}")
            except Exception as e:
                span.record_exception(e)
                await self._handle_failure(job, str(e))

    async def _execute_fresh_generation(self, job: BlogJob) -> None:
        """Run ``run_pipeline()`` over the full app pipeline for a brand-new generation.

        Agent sequence:
        - intent_agent
        - outline_agent
        - outline_review_agent
        - pause for outline confirmation when requested
        - otherwise research_agent
        - full_pipeline_draft_refinement_loop
        """
        active_version = await self._get_active_version(job.session_id)
        result = await run_pipeline(
            topic=job.topic,
            audience=job.audience,
            user_id=str(job.user_id),
            session_id=job.adk_session_id,
            state_snapshot=active_version.state_snapshot if active_version else None,
        )

        await agent_delay()

        if result.error:
            await self._handle_failure(job, result.error)
            return

        if result.paused_for_confirmation:
            await self._handle_outline_pause(job, result)
            return

        await self._handle_success(job, result)

    async def _execute_resume_outline(self, job: BlogJob) -> None:
        """Run ``resume_pipeline()`` to continue the paused full app pipeline.

        This is a true pause/resume path. The stored outline confirmation metadata is replayed
        into the paused app pipeline, which then continues with:
        - research_agent
        - full_pipeline_draft_refinement_loop
        """
        active_version = await self._get_active_version(job.session_id)
        result = await resume_pipeline(
            topic=job.topic,
            audience=job.audience,
            user_id=str(job.user_id),
            session_id=job.adk_session_id,
            invocation_id=job.invocation_id,
            confirmation_request_id=job.confirmation_request_id,
            approved_outline=job.approved_outline,
            feedback_text=job.feedback_text,
            state_snapshot=active_version.state_snapshot if active_version else None,
        )

        await agent_delay()

        if result.error:
            await self._handle_failure(job, result.error)
            return

        await self._handle_success(job, result)

    async def _execute_revision(self, job: BlogJob) -> None:
        """Run ``run_pipeline_from_phase("research_phase")`` for final-draft revision.

        This is a rerun-from-phase path, not a resume of the paused full app pipeline.
        Agent sequence:
        - research_agent
        - phase_resume_draft_refinement_loop
        """
        active_version = await self._get_active_version(job.session_id)
        result = await run_pipeline_from_phase(
            phase="research_phase",
            topic=job.topic,
            audience=job.audience,
            user_id=str(job.user_id),
            session_id=job.adk_session_id,
            state_snapshot=active_version.state_snapshot if active_version else None,
        )

        await agent_delay()

        if result.error:
            await self._handle_failure(job, result.error)
            return

        await self._handle_success(job, result)

    async def _execute_research_phase(self, job: BlogJob) -> None:
        """Run ``run_pipeline_from_phase("research_phase")`` after stale-worker recovery.

        This is a rerun-from-phase path used after outline approval has already been consumed.
        Agent sequence:
        - research_agent
        - phase_resume_draft_refinement_loop
        """
        active_version = await self._get_active_version(job.session_id)
        result = await run_pipeline_from_phase(
            phase="research_phase",
            topic=job.topic,
            audience=job.audience,
            user_id=str(job.user_id),
            session_id=job.adk_session_id,
            state_snapshot=active_version.state_snapshot if active_version else None,
        )

        await agent_delay()

        if result.error:
            await self._handle_failure(job, result.error)
            return

        await self._handle_success(job, result)

    async def _handle_outline_pause(self, job: BlogJob, result: PipelineResult) -> None:
        await self._commit_costs(job, result.costs)
        active_version = await self._get_active_version(job.session_id)
        normalized_research = self._normalize_research_data(result.research)

        snapshot = self._build_state_snapshot(job, result, feedback_text=job.feedback_text)
        if active_version:
            await self._version_repo.update_version_state(
                active_version.id,
                status=BlogSessionStatus.AWAITING_OUTLINE_REVIEW.value,
                job_phase=BlogJobPhase.RESUME_OUTLINE.value,
                title=self._extract_title(result.outline, job.topic),
                outline_data=result.outline or {},
                approved_outline=active_version.approved_outline,
                research_data=normalized_research,
                draft_content=result.draft,
                final_content=result.final_content,
                editor_review=result.editor_review,
                feedback_text=job.feedback_text or active_version.feedback_text,
                adk_session_id=job.adk_session_id,
                invocation_id=result.invocation_id,
                confirmation_request_id=result.confirmation_request_id,
                state_snapshot=snapshot,
            )

        await self._session_repo.sync_active_version_fields(
            job.session_id,
            outline_data=result.outline or {},
            invocation_id=result.invocation_id,
            confirmation_request_id=result.confirmation_request_id,
            adk_session_id=job.adk_session_id,
        )

        await self._session_repo.update_status(
            job.session_id,
            BlogSessionStatus.AWAITING_OUTLINE_REVIEW,
            current_stage="outline_review",
        )

    async def _handle_success(self, job: BlogJob, result: PipelineResult) -> None:
        normalized_research = self._normalize_research_data(result.research)
        await self._commit_costs(job, result.costs, normalized_research)
        active_version = await self._get_active_version(job.session_id)

        snapshot = self._build_state_snapshot(job, result, feedback_text=job.feedback_text)
        if active_version:
            await self._version_repo.update_version_state(
                active_version.id,
                status=BlogSessionStatus.AWAITING_FINAL_REVIEW.value,
                job_phase=job.phase,
                title=self._extract_title(result.outline, job.topic),
                outline_data=result.outline or active_version.outline_data,
                approved_outline=snapshot.get("approved_outline") or active_version.approved_outline,
                research_data=normalized_research,
                draft_content=result.draft,
                final_content=result.final_content,
                editor_review=result.editor_review,
                feedback_text=job.feedback_text or active_version.feedback_text,
                user_action=None,
                adk_session_id=job.adk_session_id,
                invocation_id=result.invocation_id or active_version.invocation_id,
                confirmation_request_id=(
                    result.confirmation_request_id or active_version.confirmation_request_id
                ),
                state_snapshot=snapshot,
            )

        if result.final_content:
            await self._session_repo.sync_active_version_fields(
                job.session_id,
                outline_data=result.outline or {},
                final_content=result.final_content,
                invocation_id=result.invocation_id or job.invocation_id,
                confirmation_request_id=(
                    result.confirmation_request_id or job.confirmation_request_id
                ),
                adk_session_id=job.adk_session_id,
            )

        await self._budget_service.release_excess(
            user_id=job.user_id, blog_session_id=job.session_id
        )

        await self._session_repo.update_status(
            job.session_id,
            BlogSessionStatus.AWAITING_FINAL_REVIEW,
            current_stage="final_review",
        )

    async def _handle_failure(self, job: BlogJob, error: str) -> None:
        active_version = await self._get_active_version(job.session_id)
        if active_version:
            await self._version_repo.update_version_state(
                active_version.id,
                status=BlogSessionStatus.FAILED.value,
                job_phase=job.phase,
                feedback_text=error,
                user_action=None,
                failed=True,
            )
        await self._session_repo.mark_failed(job.session_id, reason=error)
        await self._budget_service.release_all(user_id=job.user_id, blog_session_id=job.session_id)

    async def _commit_costs(
        self, job: BlogJob, costs: list[CostInfo], research_data: dict | None = None
    ) -> None:
        sources_list = []
        if research_data and "sources" in research_data:
            sources_list = research_data["sources"]
            if sources_list:
                await self._sources_repo.create_many(
                    blog_session_id=job.session_id,
                    sources=sources_list,
                )

        for cost in costs:
            if cost.total_tokens <= 0:
                continue

            existing = await self._run_repo.get_by_session_and_stage(job.session_id, cost.stage)
            if existing and existing.status == AgentRunStatus.COMPLETED:
                continue

            output_snapshot: dict | None = {"stage": cost.stage, "costs": cost.__dict__.copy()}

            if existing:
                latency_ms = None
                if existing.started_at:
                    latency_ms = int(
                        (datetime.now(timezone.utc) - existing.started_at).total_seconds() * 1000
                    )
                await self._run_repo.update(
                    existing.id,
                    total_tokens=cost.total_tokens,
                    cost_usd=Decimal(str(get_model_cost(cost.model, cost.total_tokens))),
                    status=AgentRunStatus.COMPLETED,
                    latency_ms=latency_ms,
                    output_snapshot=output_snapshot,
                )
                agent_run_id = existing.id
            else:
                agent_run = await self._run_repo.create(
                    blog_session_id=job.session_id,
                    stage_name=cost.stage,
                    status=AgentRunStatus.COMPLETED,
                    total_tokens=cost.total_tokens,
                    cost_usd=Decimal(str(get_model_cost(cost.model, cost.total_tokens))),
                    output_snapshot=output_snapshot,
                )
                agent_run_id = agent_run.id

            await self._budget_service.commit_stage(
                user_id=job.user_id,
                blog_session_id=job.session_id,
                agent_run_id=agent_run_id,
                actual_tokens=cost.total_tokens,
                actual_usd=Decimal(str(get_model_cost(cost.model, cost.total_tokens))),
            )

    async def _get_active_version(self, session_id: int):
        return await self._version_repo.get_active_for_session(session_id)

    def _build_state_snapshot(
        self,
        job: BlogJob,
        result: PipelineResult,
        *,
        feedback_text: str | None,
    ) -> dict:
        normalized_research = self._normalize_research_data(result.research)
        return {
            "topic": job.topic,
            "audience": job.audience,
            "intent_result": result.intent_result or {},
            "blog_outline": result.outline or {},
            "approved_outline": result.outline or job.approved_outline or {},
            "outline_feedback": feedback_text or "",
            "outline_review_result": result.confirmation_payload or {},
            "research_data": normalized_research,
            "blog_draft": result.draft or "",
            "editor_review": result.editor_review or {},
        }

    def _extract_title(self, outline: dict | None, fallback: str) -> str:
        if isinstance(outline, dict):
            title = outline.get("title")
            if isinstance(title, str) and title.strip():
                return title.strip()
        return fallback

    def _normalize_research_data(self, research_data) -> dict:
        if isinstance(research_data, dict):
            return research_data

        if isinstance(research_data, str):
            try:
                parsed = json.loads(research_data)
            except json.JSONDecodeError:
                return {}
            return parsed if isinstance(parsed, dict) else {}

        return {}
