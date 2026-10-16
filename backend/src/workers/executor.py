"""PipelineExecutor — bridges worker to ADK pipeline."""

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.pipeline import (
    CostInfo,
    PipelineResult,
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
from src.services.budget_service import BudgetService
from src.workflows.state_schema import build_session_state


class RetryableDownstreamError(Exception):
    """Transient provider/network failure eligible for bounded retry."""

#: Phases whose flow starts at research. They share a graph today but are
#: declared separately in the pipeline so the lifecycles stay distinguishable.
#:
#: ``REVISION``        -- a reviewer asked for changes
#: ``RESEARCH_PHASE``  -- outline approval or stale-worker recovery
_POST_OUTLINE_PHASES = frozenset({BlogJobPhase.REVISION.value, BlogJobPhase.RESEARCH_PHASE.value})

#: The fresh graph ends after outline normalization. The human-review wait is
#: represented by the persisted blog lifecycle, not a paused ADK invocation.
_OUTLINE_REVIEW_PHASES = frozenset({BlogJobPhase.FRESH_GENERATION.value})


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
        """Run the job's flow, then persist whatever it produced.

        Which graph runs is decided by :mod:`src.agents.pipeline` from the
        job's phase. This class owns only the second half: turning a
        :class:`PipelineResult` into durable state, and moving the session to
        whichever lifecycle state that result implies.
        """
        try:
            result = await self._run_flow(job)
        except Exception as exc:
            await self._handle_failure(job, str(exc))
            return

        await self._persist(job, result)

    async def _run_flow(self, job: BlogJob) -> PipelineResult:
        """Hand the job to the pipeline and rate-limit afterwards.

        The delay is applied here, after execution and before persistence, so
        it throttles provider call cadence without holding a transaction open.
        """
        active_version = await self._get_active_version(job.session_id)
        state_snapshot = active_version.state_snapshot if active_version else None

        if job.phase == BlogJobPhase.FRESH_GENERATION.value:
            result = await run_pipeline(
                topic=job.topic,
                audience=job.audience,
                user_id=str(job.user_id),
                session_id=job.adk_session_id,
                state_snapshot=state_snapshot,
            )
        elif job.phase in _POST_OUTLINE_PHASES or job.phase == BlogJobPhase.RESUME_OUTLINE.value:
            # Revision and stale-worker recovery share a graph today; the
            # pipeline names it, this module only reports which phase was asked
            # for. Both are "research again, then redraft".
            result = await run_pipeline_from_phase(
                phase=(
                    BlogJobPhase.RESEARCH_PHASE.value
                    if job.phase == BlogJobPhase.RESUME_OUTLINE.value
                    else job.phase
                ),
                topic=job.topic,
                audience=job.audience,
                user_id=str(job.user_id),
                session_id=job.adk_session_id,
                state_snapshot=state_snapshot,
            )
        else:
            raise ValueError(f"Unknown job phase: {job.phase}")

        await agent_delay()
        return result

    async def _persist(self, job: BlogJob, result: PipelineResult) -> None:
        """Persist outputs and move the session to the next lifecycle state."""
        if result.error:
            if result.retryable:
                raise RetryableDownstreamError(result.error)
            await self._handle_failure(job, result.error)
            return

        if job.phase in _OUTLINE_REVIEW_PHASES and result.outline:
            await self._handle_outline_review_wait(job, result)
            return

        await self._handle_success(job, result)

    async def _handle_outline_review_wait(self, job: BlogJob, result: PipelineResult) -> None:
        await self._commit_costs(job, result.costs)
        active_version = await self._get_active_version(job.session_id)
        normalized_research = self._normalize_research_data(result.research)

        snapshot = self._build_state_snapshot(job, result, feedback_text=job.feedback_text)
        if active_version:
            await self._version_repo.update_version_state(
                active_version.id,
                status=BlogSessionStatus.AWAITING_OUTLINE_REVIEW.value,
                job_phase=BlogJobPhase.RESEARCH_PHASE.value,
                title=self._extract_title(result.outline, job.topic),
                outline_data=result.outline or {},
                approved_outline=active_version.approved_outline,
                research_data=normalized_research,
                draft_content=result.draft,
                final_content=result.final_content,
                editor_review=result.editor_review,
                feedback_text=job.feedback_text or active_version.feedback_text,
                adk_session_id=job.adk_session_id,
                state_snapshot=snapshot,
            )

        await self._session_repo.sync_active_version_fields(
            job.session_id,
            outline_data=result.outline or {},
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
                approved_outline=snapshot.get("approved_outline")
                or active_version.approved_outline,
                research_data=normalized_research,
                draft_content=result.draft,
                final_content=result.final_content,
                editor_review=result.editor_review,
                feedback_text=job.feedback_text or active_version.feedback_text,
                user_action=None,
                adk_session_id=job.adk_session_id,
                state_snapshot=snapshot,
            )

        if result.final_content:
            await self._session_repo.sync_active_version_fields(
                job.session_id,
                outline_data=result.outline or {},
                final_content=result.final_content,
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

    async def fail(self, job: BlogJob, error: str) -> None:
        """Persist a terminal worker failure after retries are exhausted."""
        await self._handle_failure(job, error)


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
            if cost.total_tokens <= 0 and cost.latency_ms is None:
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
                latency_ms = cost.latency_ms if cost.latency_ms is not None else latency_ms
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
                completed_at = datetime.now(timezone.utc)
                started_at = (
                    completed_at - timedelta(milliseconds=cost.latency_ms)
                    if cost.latency_ms is not None
                    else completed_at
                )
                agent_run = await self._run_repo.create(
                    blog_session_id=job.session_id,
                    stage_name=cost.stage,
                    status=AgentRunStatus.COMPLETED,
                    total_tokens=cost.total_tokens,
                    cost_usd=Decimal(str(get_model_cost(cost.model, cost.total_tokens))),
                    latency_ms=cost.latency_ms,
                    output_snapshot=output_snapshot,
                    started_at=started_at,
                    completed_at=completed_at,
                )
                agent_run_id = agent_run.id

            if cost.total_tokens > 0:
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
        """Build the state snapshot for Postgres.

        Key names come from the shared schema so this cannot drift away from
        the session the pipeline seeded.
        """
        return build_session_state(
            topic=job.topic,
            audience=job.audience,
            intent_result=result.intent_result or {},
            blog_outline=result.outline or {},
            approved_outline=(
                job.approved_outline or {}
                if job.phase == BlogJobPhase.FRESH_GENERATION.value
                else result.outline or job.approved_outline or {}
            ),
            outline_feedback=feedback_text or "",
            outline_review_result={},
            research_data=self._normalize_research_data(result.research),
            blog_draft=result.draft or "",
            editor_review=result.editor_review or {},
        )

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
