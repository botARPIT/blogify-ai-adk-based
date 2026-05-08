"""AgentRunRepository — manages AgentRun lifecycle."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.orm_models import AgentRun, AgentRunStatus


class AgentRunRepository:
    """Create and update AgentRun records."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def start(
        self,
        blog_session_id: int,
        stage_name: str,
        agent_name: str,
        model_name: str,
        blog_version_id: Optional[int] = None,
        parent_agent_run_id: Optional[int] = None,
        input_summary: Optional[dict] = None,
    ) -> AgentRun:
        run = AgentRun(
            blog_session_id=blog_session_id,
            blog_version_id=blog_version_id,
            parent_agent_run_id=parent_agent_run_id,
            stage_name=stage_name,
            agent_name=agent_name,
            model_name=model_name,
            status=AgentRunStatus.STARTED,
            input_summary=input_summary,
        )
        self._session.add(run)
        await self._session.flush()
        return run

    async def complete(
        self,
        run_id: int,
        prompt_tokens: int,
        completion_tokens: int,
        cost_usd: float,
        latency_ms: int,
        output_summary: Optional[dict] = None,
        prompt_artifact_uri: Optional[str] = None,
        response_artifact_uri: Optional[str] = None,
    ) -> None:
        run = await self.get_by_id(run_id)
        if run:
            run.status = AgentRunStatus.COMPLETED
            run.prompt_tokens = prompt_tokens
            run.completion_tokens = completion_tokens
            run.total_tokens = prompt_tokens + completion_tokens
            run.cost_usd = cost_usd
            run.latency_ms = latency_ms
            run.output_summary = output_summary
            run.prompt_artifact_uri = prompt_artifact_uri
            run.response_artifact_uri = response_artifact_uri
            run.completed_at = datetime.now(timezone.utc)

    async def fail(
        self,
        run_id: int,
        error_message: str,
        status: AgentRunStatus = AgentRunStatus.FAILED,
    ) -> None:
        run = await self.get_by_id(run_id)
        if run:
            run.status = status
            run.error_message = error_message
            run.completed_at = datetime.now(timezone.utc)

    async def get_by_id(self, run_id: int) -> Optional[AgentRun]:
        result = await self._session.execute(
            select(AgentRun).where(AgentRun.id == run_id)
        )
        return result.scalar_one_or_none()

    async def get_for_session(self, blog_session_id: int) -> list[AgentRun]:
        result = await self._session.execute(
            select(AgentRun)
            .where(AgentRun.blog_session_id == blog_session_id)
            .order_by(AgentRun.started_at)
        )
        return list(result.scalars().all())

    async def get_completed_stages(self, blog_session_id: int) -> set[str]:
        """Return the set of stage names that completed successfully.

        Used by the worker to determine which stages can be skipped
        when resuming a session after a crash or requeue.
        """
        result = await self._session.execute(
            select(AgentRun.stage_name)
            .where(
                AgentRun.blog_session_id == blog_session_id,
                AgentRun.status == AgentRunStatus.COMPLETED,
            )
        )
        return {row[0] for row in result.all()}

    async def is_stage_completed(
        self, blog_session_id: int, stage_name: str
    ) -> bool:
        """Check whether a specific stage completed for a session."""
        result = await self._session.execute(
            select(AgentRun.id)
            .where(
                AgentRun.blog_session_id == blog_session_id,
                AgentRun.stage_name == stage_name,
                AgentRun.status == AgentRunStatus.COMPLETED,
            )
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def get_by_session_and_stage(
        self, blog_session_id: int, stage_name: str
    ) -> Optional[AgentRun]:
        result = await self._session.execute(
            select(AgentRun).where(
                AgentRun.blog_session_id == blog_session_id,
                AgentRun.stage_name == stage_name,
            )
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        blog_session_id: int,
        stage_name: str,
        agent_name: str,
        model_name: str,
        status: str = "STARTED",
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
        cost_usd: float = 0.0,
    ) -> AgentRun:
        run = AgentRun(
            blog_session_id=blog_session_id,
            stage_name=stage_name,
            agent_name=agent_name,
            model_name=model_name,
            status=status,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            cost_usd=cost_usd,
        )
        self._session.add(run)
        await self._session.flush()
        return run

    async def update(
        self,
        run_id: int,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        cost_usd: float,
        status: str,
    ) -> None:
        run = await self.get_by_id(run_id)
        if run:
            run.prompt_tokens = prompt_tokens
            run.completion_tokens = completion_tokens
            run.total_tokens = total_tokens
            run.cost_usd = cost_usd
            run.status = status
            run.completed_at = datetime.now(timezone.utc)
            await self._session.flush()
