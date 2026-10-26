"""Thin application coordinator for one claimed workflow attempt."""

from __future__ import annotations

from src.config.agent_config import agent_delay
from src.core.task_queue import BlogJob
from src.models.orm_models import BlogJobPhase
from src.workflows.contracts import WorkflowRunRequest, WorkflowRunResult
from src.workflows.runner import WorkflowRunner


class RetryableDownstreamError(Exception):
    """Transient provider or network failure eligible for bounded retry."""


class WorkflowExecutionError(Exception):
    """Terminal workflow failure that should be persisted for the user."""


class WorkflowExecutor:
    """Translate a hydrated job into a runtime request and classify its result."""

    def __init__(self, runner: WorkflowRunner | None = None) -> None:
        self._runner = runner or WorkflowRunner()

    async def execute(self, job: BlogJob) -> WorkflowRunResult:
        try:
            phase = BlogJobPhase(job.phase)
        except ValueError as exc:
            raise WorkflowExecutionError(f"Unknown job phase: {job.phase}") from exc

        result = await self._runner.run(
            WorkflowRunRequest(
                phase=phase,
                adk_session_id=job.adk_session_id,
                user_id=str(job.user_id),
                topic=job.topic,
                audience=job.audience,
                tone=job.tone,
                state_snapshot=dict(job.state_snapshot or {}),
            )
        )
        await agent_delay()

        if result.error:
            if result.retryable:
                raise RetryableDownstreamError(result.error)
            raise WorkflowExecutionError(result.error)
        return result


__all__ = [
    "RetryableDownstreamError",
    "WorkflowExecutionError",
    "WorkflowExecutor",
]
