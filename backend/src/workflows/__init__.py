"""ADK Workflow graphs for the Blogify lifecycles.

Each lifecycle gets its own module because each has one job:

* :mod:`src.workflows.fresh_generation` — topic to reviewed draft
* :mod:`src.workflows.resume_from_outline` — recovery of a job whose outline was
  already approved
* :mod:`src.workflows.revision` — a reviewer asked for changes

A workflow decides *what executes next*. Durable lifecycle state — which
session is ``AWAITING_OUTLINE_REVIEW``, which version is active — stays with the
application, not with the graph.
"""

from src.workflows.common import (
    APP_NAME,
    DEFAULT_ROUTE,
    EDITOR_REVIEW_KEY,
    INTENT_RESULT_KEY,
    MAX_REFINEMENT_ITERATIONS,
    OUTLINE_KEY,
    REFINEMENT_ITERATIONS_KEY,
    EdgeSpec,
    build_agents,
    build_app,
    build_runner,
    build_workflow,
    normalize_editor_review_node,
    normalize_intent_node,
    normalize_outline_node,
    post_outline_stages,
    pre_research_stages,
    route_after_editor,
    workflow_end,
)
from src.workflows.fresh_generation import build_fresh_generation_workflow
from src.workflows.resume_from_outline import build_resume_from_outline_workflow
from src.workflows.revision import build_revision_workflow
from src.workflows.state_schema import (
    SESSION_STATE_KEYS,
    build_session_state,
    empty_session_state,
)

__all__ = [
    "APP_NAME",
    "DEFAULT_ROUTE",
    "EDITOR_REVIEW_KEY",
    "INTENT_RESULT_KEY",
    "MAX_REFINEMENT_ITERATIONS",
    "OUTLINE_KEY",
    "REFINEMENT_ITERATIONS_KEY",
    "SESSION_STATE_KEYS",
    "EdgeSpec",
    "build_agents",
    "build_app",
    "build_fresh_generation_workflow",
    "build_resume_from_outline_workflow",
    "build_revision_workflow",
    "build_runner",
    "build_session_state",
    "build_workflow",
    "empty_session_state",
    "normalize_editor_review_node",
    "normalize_intent_node",
    "normalize_outline_node",
    "post_outline_stages",
    "pre_research_stages",
    "route_after_editor",
    "workflow_end",
]
