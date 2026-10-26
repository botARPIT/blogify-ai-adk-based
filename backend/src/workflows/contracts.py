"""Stable contracts at the boundary between workers and the ADK runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.models.orm_models import BlogJobPhase


@dataclass(frozen=True, slots=True)
class WorkflowRunRequest:
    """Everything required to execute one short-lived workflow segment."""

    phase: BlogJobPhase
    adk_session_id: str
    user_id: str
    topic: str
    audience: str
    tone: str
    state_snapshot: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class StageUsage:
    """Provider usage attributed to one logical agent stage."""

    stage: str
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_ms: int | None = None


@dataclass(slots=True)
class WorkflowRunResult:
    """Framework-neutral output returned to application orchestration."""

    adk_session_id: str
    intent_result: dict[str, Any] | None = None
    outline: dict[str, Any] | None = None
    research: dict[str, Any] | None = None
    draft: str = ""
    editor_review: dict[str, Any] | None = None
    final_content: str = ""
    usage: list[StageUsage] = field(default_factory=list)
    stage_timings_ms: dict[str, int] = field(default_factory=dict)
    error: str | None = None
    retryable: bool = False


__all__ = ["StageUsage", "WorkflowRunRequest", "WorkflowRunResult"]
