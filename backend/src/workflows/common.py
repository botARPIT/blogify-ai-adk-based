"""Shared workflow building blocks.

Everything here is deterministic: no model calls, no retry policy, no I/O. These
nodes are the boundary between "what the model said" and "what the application
does next".
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any, cast

from google.adk.agents import Agent
from google.adk.agents.context import Context
from google.adk.apps.app import App
from google.adk.runners import Runner
from google.adk.workflow import DEFAULT_ROUTE, Workflow

from src.agents.editor_agent import create_editor_agent
from src.agents.intent_agent import create_intent_agent
from src.agents.outline_agent import create_outline_agent
from src.agents.research_agent import create_research_agent
from src.agents.writer_agent import create_writer_agent
from src.config.logging_config import get_logger
from src.monitoring.metrics import judge_decisions_total, validation_failures_total
from src.normalizer import (
    NormalizationError,
    extract_raw_output,
    normalize_editor_review,
    normalize_intent,
    normalize_outline,
    normalize_research,
)
from src.workflows.state_schema import (
    EDITOR_REVIEW_KEY as _EDITOR_REVIEW_KEY,
)
from src.workflows.state_schema import (
    INTENT_RESULT_KEY as _INTENT_RESULT_KEY,
)
from src.workflows.state_schema import (
    OUTLINE_KEY as _OUTLINE_KEY,
)
from src.workflows.state_schema import (
    REFINEMENT_ITERATIONS_KEY as _REFINEMENT_ITERATIONS_KEY,
)
from src.workflows.state_schema import (
    RESEARCH_DATA_KEY as _RESEARCH_DATA_KEY,
)
from src.workflows.state_schema import (
    RESEARCH_TOOL_DATA_KEY as _RESEARCH_TOOL_DATA_KEY,
)

logger = get_logger(__name__)

APP_NAME = "blogify"

#: How many times the writer/editor cycle may run before the draft is accepted.
#: Replaces the old ``LoopAgent(max_iterations=2)``: the same bound, but now a
#: value the graph reasons about instead of a scheduler setting.
MAX_REFINEMENT_ITERATIONS = 2

#: Session state key names live in state_schema so the pipeline and the executor
#: cannot drift apart. Re-exported here because graph nodes read them constantly.
INTENT_RESULT_KEY = _INTENT_RESULT_KEY
OUTLINE_KEY = _OUTLINE_KEY
EDITOR_REVIEW_KEY = _EDITOR_REVIEW_KEY
REFINEMENT_ITERATIONS_KEY = _REFINEMENT_ITERATIONS_KEY
RESEARCH_DATA_KEY = _RESEARCH_DATA_KEY
RESEARCH_TOOL_DATA_KEY = _RESEARCH_TOOL_DATA_KEY


# ---------------------------------------------------------------------------
# Deterministic normalization nodes
# ---------------------------------------------------------------------------


def normalize_intent_node(ctx: Context, node_input: Any) -> dict[str, Any]:
    """Turn the intent classifier's raw output into ``intent_result``."""
    raw = _raw_text(ctx, node_input, "intent_raw")
    try:
        intent = normalize_intent(raw)
    except NormalizationError:
        validation_failures_total.labels(
            agent_name="intent_classifier", validation_type="output_schema"
        ).inc()
        raise
    payload = intent.model_dump()
    ctx.state[INTENT_RESULT_KEY] = payload
    return payload


def route_after_intent(ctx: Context) -> str:
    """Continue only when the deterministic intent gate accepted the request."""
    intent = ctx.state.get(INTENT_RESULT_KEY)
    is_clear = intent.get("intent_clear") if isinstance(intent, dict) else False
    ctx.route = "clear" if is_clear is True else "blocked"
    return str(ctx.route)


def normalize_outline_node(ctx: Context, node_input: Any) -> dict[str, Any]:
    """Turn the outline agent's raw output into ``blog_outline``.

    On invalid output this raises :class:`NormalizationError`. The failure is
    deliberate and total: bad model output must not silently become empty state
    and continue into a human review that would present a blank outline.
    """
    raw = _raw_text(ctx, node_input, "outline_raw")
    try:
        outline = normalize_outline(raw)
    except NormalizationError:
        validation_failures_total.labels(
            agent_name="outline_agent", validation_type="output_schema"
        ).inc()
        raise
    payload = outline.model_dump()
    ctx.state[OUTLINE_KEY] = payload
    return payload


def normalize_editor_review_node(ctx: Context, node_input: Any) -> dict[str, Any]:
    """Turn the editor's raw output into ``editor_review``."""
    raw = _raw_text(ctx, node_input, "editor_review_raw")
    try:
        review = normalize_editor_review(raw)
    except NormalizationError:
        validation_failures_total.labels(
            agent_name="editor_agent", validation_type="output_schema"
        ).inc()
        raise
    payload = review.model_dump()
    try:
        _validate_editor_citations(payload, ctx.state.get(RESEARCH_DATA_KEY))
    except NormalizationError:
        validation_failures_total.labels(
            agent_name="editor_agent", validation_type="citation_rule"
        ).inc()
        raise
    judge_decisions_total.labels(
        decision="approved" if payload.get("approved") else "rejected"
    ).inc()
    ctx.state[EDITOR_REVIEW_KEY] = payload
    return payload


def normalize_research_node(ctx: Context, node_input: Any) -> dict[str, Any]:
    """Commit only validated evidence into the state visible to later agents."""
    tool_payload = ctx.state.get(RESEARCH_TOOL_DATA_KEY)
    raw = tool_payload if isinstance(tool_payload, dict) else _raw_text(
        ctx,
        node_input,
        "research_data_raw",
    )
    try:
        research = normalize_research(raw)
    except NormalizationError:
        validation_failures_total.labels(
            agent_name="research_agent", validation_type="output_schema"
        ).inc()
        raise
    payload = research.model_dump()
    ctx.state[RESEARCH_DATA_KEY] = payload
    return payload


def _raw_text(ctx: Context, node_input: Any, state_key: str) -> str:
    """Read raw model text from the node input, falling back to session state.

    ``node_input`` is the predecessor's output. Session state is checked as a
    fallback because an agent that produced no output leaves the edge input
    empty while its ``output_key`` may still hold a value from the same run.
    """
    raw = extract_raw_output(node_input)
    if raw.strip():
        return raw

    stored = ctx.state.get(state_key)
    if isinstance(stored, str):
        return stored
    if stored is not None:
        return extract_raw_output(stored)
    return raw


def _validate_editor_citations(review: dict[str, Any], research_data: Any) -> None:
    """Reject final content that cites an index outside validated research."""
    if not review.get("approved"):
        return
    sources = research_data.get("sources", []) if isinstance(research_data, dict) else []
    source_count = len(sources)
    references = {int(index) for index in re.findall(r"\[(\d{1,2})\]", review.get("final_blog", ""))}
    invalid = sorted(index for index in references if index < 1 or index > source_count)
    if invalid:
        raise NormalizationError(
            workflow="blog_generation",
            stage="editor",
            agent="editor_agent",
            output_format="json",
            reason="final_blog cites a source outside validated research_data",
            field_paths=[f"final_blog.citation[{index}]" for index in invalid],
        )


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------


def route_after_editor(ctx: Context) -> str:
    """Decide whether the writer runs again or the draft is accepted.

    Emits ``revise`` or ``approve``. The cycle is bounded by
    :data:`MAX_REFINEMENT_ITERATIONS`: once the bound is reached the draft is
    accepted regardless of the verdict, which is what the previous
    ``LoopAgent(max_iterations=2)`` did when it ran out of iterations.
    """
    attempts = int(ctx.state.get(REFINEMENT_ITERATIONS_KEY, 0)) + 1
    ctx.state[REFINEMENT_ITERATIONS_KEY] = attempts

    review = ctx.state.get(EDITOR_REVIEW_KEY) or {}
    approved = bool(review.get("approved"))

    if attempts >= MAX_REFINEMENT_ITERATIONS:
        logger.info(
            "refinement_bound_reached",
            attempts=attempts,
            approved=approved,
        )
        ctx.route = "approve"
        return "approve"

    ctx.route = "approve" if approved else "revise"
    return str(ctx.route)


def workflow_end(ctx: Context) -> str:
    """Terminal node: the graph ran to completion."""
    return "completed"


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------


#: An edge item as accepted by :class:`~google.adk.workflow.Workflow`: either
#: two nodes in sequence, or a node followed by a route -> destination map.
EdgeSpec = Sequence[Any]


def build_workflow(name: str, edges: Sequence[EdgeSpec]) -> Workflow:
    """Construct a :class:`Workflow` from declarative edge specs.

    ADK types ``Workflow.edges`` as an invariant ``list`` of a union that is not
    exported from ``google.adk.workflow``. The cast is confined to this one
    function rather than sprinkled across the graph builders: the specs are
    valid by construction here, and ADK validates the graph at build time
    anyway.
    """
    return Workflow(name=name, edges=cast("Any", edges))


def _editor_cycle(writer: Agent, editor: Agent) -> list[EdgeSpec]:
    """The writer/editor refinement cycle as explicit conditional edges.

    ``writer -> editor -> normalize -> route`` with a single conditional edge
    back to the writer. ADK rejects unconditional cycles, and this edge is
    routed, which is exactly the guarantee the loop needs.
    """
    return [
        (writer, editor),
        (editor, normalize_editor_review_node),
        (normalize_editor_review_node, route_after_editor),
        (route_after_editor, {"revise": writer}),
        (route_after_editor, {"approve": workflow_end}),
    ]


def build_agents(names: Sequence[str] | None = None) -> dict[str, Agent]:
    """Construct only the agents a graph uses.

    Omitting ``names`` builds the full set for fresh generation. Post-outline
    graphs pass their smaller set so unused agents and their model adapters are
    not created for those runs.
    """
    factories = {
        "intent": create_intent_agent,
        "outline": create_outline_agent,
        "research": create_research_agent,
        "writer": create_writer_agent,
        "editor": create_editor_agent,
    }
    selected = tuple(factories) if names is None else tuple(names)
    unknown = set(selected) - factories.keys()
    if unknown:
        raise ValueError(f"Unknown workflow agents: {', '.join(sorted(unknown))}")
    return {name: factories[name]() for name in selected}


# ---------------------------------------------------------------------------
# Stage fragments
#
# A flow declares its own edges; these cover the stages that genuinely repeat
# across flows. Each fragment leaves its endpoints open so the caller controls
# what enters and what leaves.
# ---------------------------------------------------------------------------


def pre_research_stages(agents: dict[str, Agent]) -> list[EdgeSpec]:
    """START -> intent gate -> outline, with normalization nodes after each agent.

    Ends after outline normalization. Fresh generation terminates there so the
    application can persist the outline for human review.
    """
    intent = agents["intent"]
    outline = agents["outline"]
    return [
        ("START", intent),
        (intent, normalize_intent_node),
        (normalize_intent_node, route_after_intent),
        (route_after_intent, {"clear": outline, "blocked": workflow_end}),
        (outline, normalize_outline_node),
    ]


def post_outline_stages(agents: dict[str, Agent]) -> list[EdgeSpec]:
    """research -> validate evidence -> writer -> editor, ending at the terminal node.

    Starts at research. Post-outline workflows own the edge that reaches it.
    """
    research = agents["research"]
    writer = agents["writer"]
    editor = agents["editor"]

    return [
        (research, normalize_research_node),
        (normalize_research_node, writer),
        *_editor_cycle(writer, editor),
    ]


def build_post_outline_workflow(name: str) -> Workflow:
    """Build the shared graph used by revision and post-outline recovery."""
    agents = build_agents(("research", "writer", "editor"))
    return build_workflow(
        name,
        [
            ("START", agents["research"]),
            *post_outline_stages(agents),
        ],
    )


def build_app(root_agent: Workflow) -> App:
    """Wrap one short-lived workflow segment in an ADK application."""
    return App(name=APP_NAME, root_agent=root_agent)


def build_runner(app: App, session_service: Any) -> Runner:
    return Runner(app=app, app_name=APP_NAME, session_service=session_service)


__all__ = [
    "APP_NAME",
    "DEFAULT_ROUTE",
    "EDITOR_REVIEW_KEY",
    "INTENT_RESULT_KEY",
    "MAX_REFINEMENT_ITERATIONS",
    "NormalizationError",
    "OUTLINE_KEY",
    "REFINEMENT_ITERATIONS_KEY",
    "RESEARCH_DATA_KEY",
    "RESEARCH_TOOL_DATA_KEY",
    "EdgeSpec",
    "build_agents",
    "build_app",
    "build_post_outline_workflow",
    "build_runner",
    "build_workflow",
    "normalize_editor_review_node",
    "normalize_intent_node",
    "normalize_outline_node",
    "normalize_research_node",
    "post_outline_stages",
    "pre_research_stages",
    "route_after_editor",
    "route_after_intent",
    "workflow_end",
]
