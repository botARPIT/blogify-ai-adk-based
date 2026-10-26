"""Single registry mapping durable job phases to ADK workflow definitions."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from google.adk.workflow import Workflow

from src.models.orm_models import BlogJobPhase
from src.workflows.fresh_generation import build_fresh_generation_workflow
from src.workflows.post_outline import build_continue_after_outline_workflow
from src.workflows.revision import build_revision_workflow

WorkflowBuilder = Callable[[], Workflow]


@dataclass(frozen=True, slots=True)
class WorkflowSpec:
    builder: WorkflowBuilder
    prompt_label: str


WORKFLOW_SPECS: dict[BlogJobPhase, WorkflowSpec] = {
    BlogJobPhase.FRESH_GENERATION: WorkflowSpec(
        builder=build_fresh_generation_workflow,
        prompt_label="Generate a blog outline",
    ),
    BlogJobPhase.RESEARCH_PHASE: WorkflowSpec(
        builder=build_continue_after_outline_workflow,
        prompt_label="Continue from the approved outline",
    ),
    BlogJobPhase.REVISION: WorkflowSpec(
        builder=build_revision_workflow,
        prompt_label="Revise the blog using the review feedback",
    ),
}


def get_workflow_spec(phase: BlogJobPhase) -> WorkflowSpec:
    try:
        return WORKFLOW_SPECS[phase]
    except KeyError as exc:
        raise ValueError(f"Unsupported workflow phase: {phase.value}") from exc


__all__ = ["WORKFLOW_SPECS", "WorkflowBuilder", "WorkflowSpec", "get_workflow_spec"]
