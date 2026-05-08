"""PipelineExecutor — bridges worker to ADK pipeline."""

from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.pipeline import (
    CostInfo,
    PipelineResult,
    resume_pipeline,
    run_pipeline,
)
from src.config.budget_config import get_model_cost
from src.core.task_queue import BlogJob
from src.models.orm_models import AgentRun, AgentRunStatus, BlogSessionStatus
from src.models.repositories.agent_run_repository import AgentRunRepository
from src.models.repositories.blog_session_repository import BlogSessionRepository
from src.models.repositories.budget_repository import BudgetRepository
from src.services.budget_service import BudgetService


class PipelineExecutor:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._session_repo = BlogSessionRepository(session)
        self._run_repo = AgentRunRepository(session)
        self._budget_repo = BudgetRepository(session)
        self._budget_service = BudgetService(self._budget_repo, self._session_repo)

    async def execute(self, job: BlogJob) -> None:
        try:
            if job.phase == "start":
                await self._execute_start(job)
            elif job.phase == "resume_outline":
                await self._execute_resume_outline(job)
            else:
                raise ValueError(f"Unknown job phase: {job.phase}")
        except Exception as e:
            await self._handle_failure(job, str(e))

    async def _execute_start(self, job: BlogJob) -> None:
        await self._session_repo.update_status(
            job.session_id, BlogSessionStatus.PROCESSING, current_stage="intent"
        )

        result = await run_pipeline(
            topic=job.topic,
            audience=job.audience,
            user_id=str(job.user_id),
            session_id=job.adk_session_id,
        )

        if result.error:
            await self._handle_failure(job, result.error)
            return

        if result.paused_for_confirmation:
            await self._handle_outline_pause(job, result)
            return

        await self._handle_success(job, result)

    async def _execute_resume_outline(self, job: BlogJob) -> None:
        await self._session_repo.update_status(
            job.session_id, BlogSessionStatus.PROCESSING, current_stage="research"
        )

        result = await resume_pipeline(
            topic=job.topic,
            audience=job.audience,
            user_id=str(job.user_id),
            session_id=job.adk_session_id,
            invocation_id=job.invocation_id,
            confirmation_request_id=job.confirmation_request_id,
            approved_outline=job.approved_outline,
            feedback_text=job.feedback_text,
        )

        if result.error:
            await self._handle_failure(job, result.error)
            return

        await self._handle_success(job, result)

    async def _handle_outline_pause(
        self, job: BlogJob, result: PipelineResult
    ) -> None:
        await self._commit_costs(job, result.costs)

        await self._session_repo.save_outline(
            session_id=job.session_id,
            outline_data=result.outline,
            invocation_id=result.invocation_id,
            confirmation_request_id=result.confirmation_request_id,
        )

        await self._session_repo.update_status(
            job.session_id,
            BlogSessionStatus.AWAITING_OUTLINE_REVIEW,
            current_stage="outline_review",
        )

    async def _handle_success(self, job: BlogJob, result: PipelineResult) -> None:
        await self._commit_costs(job, result.costs)

        if result.final_content:
            await self._session_repo.save_final_content(
                job.session_id, result.final_content
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
        await self._session_repo.mark_failed(job.session_id, reason=error)
        await self._budget_service.release_all(
            user_id=job.user_id, blog_session_id=job.session_id
        )

    async def _commit_costs(
        self, job: BlogJob, costs: list[CostInfo]
    ) -> None:
        for cost in costs:
            if cost.total_tokens <= 0:
                continue

            existing = await self._run_repo.get_by_session_and_stage(
                job.session_id, cost.stage
            )
            if existing and existing.status == AgentRunStatus.COMPLETED.value:
                continue

            if existing:
                await self._run_repo.update(
                    existing.id,
                    prompt_tokens=cost.prompt_tokens,
                    completion_tokens=cost.completion_tokens,
                    total_tokens=cost.total_tokens,
                    cost_usd=Decimal(str(get_model_cost(cost.model, cost.total_tokens))),
                    status=AgentRunStatus.COMPLETED.value,
                )
                agent_run_id = existing.id
            else:
                agent_run = await self._run_repo.create(
                    blog_session_id=job.session_id,
                    stage_name=cost.stage,
                    agent_name=cost.stage,
                    model_name=cost.model,
                    status=AgentRunStatus.COMPLETED.value,
                    prompt_tokens=cost.prompt_tokens,
                    completion_tokens=cost.completion_tokens,
                    total_tokens=cost.total_tokens,
                    cost_usd=Decimal(str(get_model_cost(cost.model, cost.total_tokens))),
                )
                agent_run_id = agent_run.id

            await self._budget_service.commit_stage(
                user_id=job.user_id,
                blog_session_id=job.session_id,
                agent_run_id=agent_run_id,
                actual_tokens=cost.total_tokens,
                actual_usd=Decimal(str(get_model_cost(cost.model, cost.total_tokens))),
            )