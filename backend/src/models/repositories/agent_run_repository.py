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
