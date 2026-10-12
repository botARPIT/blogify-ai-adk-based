"""Resume-from-outline workflow.

The post-outline half of the lifecycle::

    START
      -> Research
      -> Writer
      -> Editor
      -> Normalize Editor
      -> route_after_editor --revise--> Writer
                          --approve--> end

This is the graph behind ``run_pipeline_from_phase("research_phase")``. It is
the same shape used when a worker recovers a job whose outline was already
approved, so it deliberately starts at research: re-running the outline would
discard the reviewer's edits and re-ask a question they already answered.
"""

from __future__ import annotations

from google.adk.workflow import Workflow

from src.workflows.common import build_post_outline_workflow

WORKFLOW_NAME = "blog_resume_from_outline"


def build_resume_from_outline_workflow() -> Workflow:
    """Build the post-outline graph used for recovery and phase resumes."""
    return build_post_outline_workflow(WORKFLOW_NAME)
