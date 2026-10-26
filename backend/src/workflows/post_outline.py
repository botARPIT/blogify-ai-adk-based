"""Post-outline workflow used after a human approves an outline."""

from __future__ import annotations

from google.adk.workflow import Workflow

from src.workflows.common import build_post_outline_workflow

WORKFLOW_NAME = "blog_continue_after_outline"


def build_continue_after_outline_workflow() -> Workflow:
    """Run research, writing, and editorial refinement from a durable snapshot."""
    return build_post_outline_workflow(WORKFLOW_NAME)


__all__ = ["WORKFLOW_NAME", "build_continue_after_outline_workflow"]
