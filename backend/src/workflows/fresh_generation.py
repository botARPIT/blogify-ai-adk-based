"""Fresh generation workflow.

The first lifecycle segment, from a topic to a reviewable outline::

    START
      -> Intent
      -> Normalize Intent
      -> Outline
      -> Normalize Outline
      -> Outline review        (workflow ends; app persists for human review)

    After approval, the API enqueues a new post-outline invocation from the
    persisted outline snapshot.

Only this flow runs the pre-research stages. The revision and recovery flows
reuse the post-outline half because their outline was already approved.

The outline review boundary belongs to the application lifecycle, not to an ADK
confirmation. The graph ends after outline normalization, allowing the worker to
persist the outline and release its lease while the user decides.
"""

from __future__ import annotations

from google.adk.workflow import Workflow

from src.workflows.common import (
    EdgeSpec,
    build_agents,
    build_workflow,
    normalize_outline_node,
    pre_research_stages,
    workflow_end,
)

WORKFLOW_NAME = "blog_generation"


def build_fresh_generation_workflow() -> Workflow:
    """Build the graph that classifies a request and generates its outline."""
    agents = build_agents(("intent", "outline"))

    edges: list[EdgeSpec] = [
        *pre_research_stages(agents),
        (normalize_outline_node, workflow_end),
    ]

    return build_workflow(WORKFLOW_NAME, edges)
