"""AgentRunRepository — manages AgentRun lifecycle."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from decimal import Decimal
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.orm_models import AgentRun, AgentRunStatus


class AgentRunRepository:
    """Create and update AgentRun records."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def session(self) -> AsyncSession:
        return self._session

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
                AgentRun.status == AgentRunStatus.COMPLETED.value,
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
                AgentRun.status == AgentRunStatus.COMPLETED.value,
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
        user_id: int,
        blog_session_id: int,
        stage_name: str,
        agent_name: str,
        model_name: str,
        status: str = "STARTED",
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
        cost_usd: float = 0.0,
        latency_ms: Optional[int] = None,
        output_snapshot: Optional[dict] = None,
    ) -> AgentRun:
        run = AgentRun(
            user_id=user_id,
            blog_session_id=blog_session_id,
            stage_name=stage_name,
            agent_name=agent_name,
            model_name=model_name,
            status=status,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            cost_usd=Decimal(str(cost_usd)),
            latency_ms=latency_ms,
            output_snapshot=output_snapshot,
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
        latency_ms: Optional[int] = None,
        output_snapshot: Optional[dict] = None,
    ) -> None:
        run = await self.get_by_id(run_id)
        if run:
            run.prompt_tokens = prompt_tokens
            run.completion_tokens = completion_tokens
            run.total_tokens = total_tokens
            run.cost_usd = Decimal(str(cost_usd))
            run.status = status
            run.latency_ms = latency_ms
            run.output_snapshot = output_snapshot
            run.completed_at = datetime.now(timezone.utc)
            await self._session.flush()

    async def get_duration_ms(self, run_id: int) -> Optional[int]:
        """Get the duration of an agent run in milliseconds."""
        run = await self.get_by_id(run_id)
        if run and run.completed_at and run.started_at:
            return int((run.completed_at - run.started_at).total_seconds() * 1000)
        return None

    async def get_output_snapshot(self, run_id: int) -> Optional[dict]:
        """Get the output snapshot for an agent run."""
        run = await self.get_by_id(run_id)
        return run.output_snapshot if run else None

    async def get_session_timeline(
        self, blog_session_id: int
    ) -> list[dict]:
        """Get timeline of all agent runs for a session with timing info."""
        runs = await self.get_for_session(blog_session_id)
        timeline = []
        for run in runs:
            duration_ms = None
            if run.completed_at and run.started_at:
                duration_ms = int((run.completed_at - run.started_at).total_seconds() * 1000)
            timeline.append({
                "run_id": run.id,
                "stage_name": run.stage_name,
                "agent_name": run.agent_name,
                "model_name": run.model_name,
                "status": run.status,
                "prompt_tokens": run.prompt_tokens,
                "completion_tokens": run.completion_tokens,
                "total_tokens": run.total_tokens,
                "cost_usd": float(run.cost_usd),
                "latency_ms": run.latency_ms or duration_ms,
                "started_at": run.started_at.isoformat() if run.started_at else None,
                "completed_at": run.completed_at.isoformat() if run.completed_at else None,
                "error_message": run.error_message,
            })
        return timeline
