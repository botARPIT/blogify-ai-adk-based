"""Blog pipeline execution.

This module is the public surface the worker already depends on
(``run_pipeline`` and ``run_pipeline_from_phase``) and owns
everything between the queue and the graph: session synchronisation, event
collection, and the mapping from ADK events to application results.

The execution graph itself lives in :mod:`src.workflows`. Orchestration and
durable lifecycle state are kept apart on purpose — a worker learns which
workflow to run, never how the graph is wired internally.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from google.adk.events import Event, EventActions
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from src.config.logging_config import get_logger
from src.core.sanitization import sanitize_audience, sanitize_topic
from src.monitoring.tracing import trace_span
from src.workflows.common import APP_NAME, build_app, build_runner
from src.workflows.fresh_generation import build_fresh_generation_workflow
from src.workflows.resume_from_outline import build_resume_from_outline_workflow
from src.workflows.revision import build_revision_workflow
from src.workflows.state_schema import (
    EDITOR_REVIEW_KEY,
    INTENT_RESULT_KEY,
    OUTLINE_KEY,
    empty_session_state,
)

logger = get_logger(__name__)

#: ``job_phase`` -> workflow builder. This map is the whole of flow selection:
#: the worker names a phase, this module names the graph. Revision and recovery
#: share an identical graph today but are declared separately, so naming them
#: apart keeps the distinction visible and lets them diverge later.
PHASE_WORKFLOWS = {
    "research_phase": build_resume_from_outline_workflow,
    "revision": build_revision_workflow,
}


@dataclass
class CostInfo:
    stage: str
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    research_sources: list[dict] = None

    def __post_init__(self):
        if self.research_sources is None:
            self.research_sources = []


@dataclass
class PipelineResult:
    session_id: str
    intent_result: dict[str, Any] | None = None
    outline: dict[str, Any] | None = None
    research: dict[str, Any] | None = None
    draft: str = ""
    editor_review: dict[str, Any] | None = None
    final_content: str = ""
    costs: list[CostInfo] = field(default_factory=list)
    error: str | None = None
    retryable: bool = False

    #: Persisted state to merge into the session before the flow runs. Carried
    #: on the result so every entrypoint hands the same thing to the executor,
    #: which is the only other consumer of it.
    state_snapshot: dict[str, Any] | None = field(default=None, repr=False)


# ---------------------------------------------------------------------------
# Application / runner
# ---------------------------------------------------------------------------

APP = build_app(build_fresh_generation_workflow())

STAGE_BY_AUTHOR = {
    "intent_classifier": "intent",
    "outline_agent": "outline",
    "research_agent": "research",
    "writer_agent": "writer",
    "editor_agent": "editor",
}


def _build_runner(session_service: Any) -> Runner:
    return build_runner(APP, session_service)


def _build_phase_runner(session_service: Any, phase: str) -> Runner:
    """Build a runner for a post-outline phase.

    Post-outline phases use a new invocation seeded with the state snapshot
    saved on the active blog version. This avoids depending on event history
    from the completed outline-generation invocation.
    """
    builder = PHASE_WORKFLOWS.get(phase)
    if builder is None:
        raise ValueError(f"Unsupported pipeline phase: {phase}")

    phase_app = build_app(builder())
    return build_runner(phase_app, session_service)


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------


def _initial_state(topic: str, audience: str) -> dict[str, Any]:
    """Seed a new session's state from the shared schema."""
    return empty_session_state(topic, audience)


async def _ensure_session(
    *,
    svc: Any,
    session_id: str,
    user_id: str,
    safe_topic: str,
    safe_audience: str,
    state_snapshot: dict[str, Any] | None,
) -> Any:
    session = await svc.get_session(
        app_name=APP_NAME,
        user_id=user_id,
        session_id=session_id,
    )
    if session is not None:
        if state_snapshot:
            await svc.append_event(
                session,
                Event(
                    author="workflow_snapshot",
                    actions=EventActions(state_delta=state_snapshot),
                ),
            )
        return session

    initial_state = _initial_state(safe_topic, safe_audience)
    if state_snapshot:
        initial_state.update(state_snapshot)

    return await svc.create_session(
        app_name=APP_NAME,
        user_id=user_id,
        session_id=session_id,
        state=initial_state,
    )


def _populate_result_from_state(result: PipelineResult, state: dict[str, Any]) -> None:
    state.setdefault("intent_result", {})
    state.setdefault("blog_outline", {})
    state.setdefault("research_data", {})
    state.setdefault("blog_draft", "")
    state.setdefault("editor_review", {})
    result.intent_result = state.get("intent_result")
    result.outline = state.get("blog_outline")
    result.research = state.get("research_data")
    result.draft = state.get("blog_draft", "")
    result.editor_review = state.get("editor_review")


# ---------------------------------------------------------------------------
# Event handling
# ---------------------------------------------------------------------------


def _usage_from_event(event: Any) -> tuple[str | None, Any | None]:
    author = getattr(event, "author", None)
    meta = getattr(event, "usage_metadata", None)
    if meta is None:
        content = getattr(event, "content", None)
        if content:
            meta = getattr(content, "usage_metadata", None)
    return author, meta


def _extract_costs_from_events(events: list[Any]) -> list[CostInfo]:
    costs: dict[str, CostInfo] = {}
    for event in events:
        author, meta = _usage_from_event(event)
        if meta is None:
            continue

        stage = STAGE_BY_AUTHOR.get(author or "")
        if stage is None:
            continue

        cost = costs.setdefault(stage, CostInfo(stage=stage))
        cost.prompt_tokens += getattr(meta, "prompt_token_count", 0) or 0
        cost.completion_tokens += getattr(meta, "candidates_token_count", 0) or 0
        cost.total_tokens += getattr(meta, "total_token_count", 0) or 0
        cost.model = getattr(meta, "model_id", "") or cost.model

    if costs:
        ordered = ["intent", "outline", "research", "writer", "editor"]
        return [costs[stage] for stage in ordered if stage in costs]

    fallback = CostInfo(stage="full_pipeline")
    for event in events:
        _, meta = _usage_from_event(event)
        if meta:
            fallback.prompt_tokens += getattr(meta, "prompt_token_count", 0) or 0
            fallback.completion_tokens += getattr(meta, "candidates_token_count", 0) or 0
            fallback.total_tokens += getattr(meta, "total_token_count", 0) or 0
            fallback.model = getattr(meta, "model_id", "") or fallback.model
    return [fallback] if fallback.total_tokens else []


async def _run_runner(
    *,
    runner: Runner,
    user_id: str,
    session_id: str,
    new_message: types.Content | None,
) -> list[Any]:
    events: list[Any] = []
    async for event in runner.run_async(
        user_id=user_id,
        session_id=session_id,
        new_message=new_message,
    ):
        events.append(event)
        logger.debug(
            "pipeline_event",
            author=getattr(event, "author", "?"),
        )
    return events


async def _finalize_result(
    *,
    svc: Any,
    result: PipelineResult,
    user_id: str,
    session_id: str,
    events: list[Any],
) -> PipelineResult:
    latest_session = await svc.get_session(
        app_name=APP_NAME,
        user_id=user_id,
        session_id=session_id,
    )
    state = latest_session.state if latest_session and hasattr(latest_session, "state") else {}
    _populate_result_from_state(result, state)

    editor_review = result.editor_review
    if isinstance(editor_review, dict) and editor_review.get("approved"):
        result.final_content = editor_review.get("final_blog", result.draft)
    else:
        result.final_content = result.draft

    result.costs.extend(_extract_costs_from_events(events))
    logger.info(
        "pipeline_completed",
        session_id=session_id,
        total_tokens=sum(cost.total_tokens for cost in result.costs),
        has_final_content=bool(result.final_content),
    )
    return result


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------


def _build_initial_message(topic: str, audience: str) -> types.Content:
    return types.Content(
        role="user",
        parts=[
            types.Part(text=(f"Generate a blog post about: {topic}\nTarget audience: {audience}"))
        ],
    )


def _build_phase_message(phase: str, topic: str, audience: str) -> types.Content:
    return types.Content(
        role="user",
        parts=[
            types.Part(
                text=(
                    f"Continue blog generation from {phase}.\n"
                    f"Topic: {topic}\n"
                    f"Target audience: {audience}"
                )
            )
        ],
    )


# ---------------------------------------------------------------------------
# Flow execution
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _FlowRequest:
    """What every flow needs to start: who, what, and from which session.

    Bundled because all four entrypoints take the same inputs; passing them as
    eight keywords to a shared helper repeated more than it decided.
    """

    topic: str
    session_id: str
    audience: str
    user_id: str
    session_service: Any | None
    state_snapshot: dict[str, Any] | None


async def _execute(
    request: _FlowRequest,
    *,
    span_name: str,
    error_event: str,
    build_runner: Callable[[Any], Runner] | None,
    build_message: Callable[[Any, str], types.Content] | None = None,
    span_attributes: dict[str, Any] | None = None,
) -> PipelineResult:
    """Run a flow end to end and return its result.

    Owns the sequence every entrypoint shares: make sure the session exists,
    merge any persisted snapshot into it, run the graph, translate the events
    into a :class:`PipelineResult`, and turn any failure into ``result.error``
    rather than an exception the caller must handle.

    ``build_runner`` and ``build_message`` are factories rather than values
    because constructing either can fail -- an unknown phase, or an approved
    outline that does not validate -- and those failures belong inside this
    error boundary, exactly as they were when each entrypoint built its own
    runner and message under the same ``try``. A ``None`` runner selects a
    state-only read, which reuses this path without executing a graph.
    """
    # ADK state is invocation-local. Durable state for later invocations comes
    # from the PostgreSQL blog-version snapshot, so no Redis session history is
    # needed across the human-review boundary.
    svc = request.session_service or InMemorySessionService()
    safe_topic = sanitize_topic(request.topic)
    safe_audience = sanitize_audience(request.audience)
    result = PipelineResult(session_id=request.session_id, state_snapshot=request.state_snapshot)
    attributes = {
        "user_id": request.user_id,
        "session_id": request.session_id,
        **(span_attributes or {}),
    }

    with trace_span(span_name, attributes=attributes):
        try:
            await _ensure_session(
                svc=svc,
                session_id=request.session_id,
                user_id=request.user_id,
                safe_topic=safe_topic,
                safe_audience=safe_audience,
                state_snapshot=request.state_snapshot,
            )

            events: list[Any] = []
            if build_runner is not None:
                events = await _run_runner(
                    runner=build_runner(svc),
                    user_id=request.user_id,
                    session_id=request.session_id,
                    new_message=(
                        build_message(safe_topic, safe_audience) if build_message else None
                    ),
                )

            return await _finalize_result(
                svc=svc,
                result=result,
                user_id=request.user_id,
                session_id=request.session_id,
                events=events,
            )
        except Exception as exc:
            result.error = str(exc)
            result.retryable = _is_transient_downstream_error(exc)
            logger.error(
                error_event,
                session_id=request.session_id,
                error=str(exc),
                exc_info=True,
                **(span_attributes or {}),
            )
            return result


def _is_transient_downstream_error(exc: Exception) -> bool:
    """Recognize retryable provider/network failures without retrying bad input."""
    transient_names = {
        "TimeoutError",
        "TimeoutException",
        "ConnectError",
        "ConnectionError",
        "ServiceUnavailable",
        "DeadlineExceeded",
        "ResourceExhausted",
        "TooManyRequests",
        "InternalServerError",
    }
    current: BaseException | None = exc
    while current is not None:
        if type(current).__name__ in transient_names:
            return True
        status_code = getattr(current, "status_code", None) or getattr(current, "code", None)
        try:
            status_code = int(status_code)
        except (TypeError, ValueError):
            pass
        if status_code == 429 or (isinstance(status_code, int) and 500 <= status_code < 600):
            return True
        current = current.__cause__ or current.__context__
    return False


async def run_pipeline(
    topic: str,
    session_id: str,
    audience: str = "general readers",
    user_id: str = "anonymous",
    session_service: Any | None = None,
    state_snapshot: dict[str, Any] | None = None,
) -> PipelineResult:
    """Run topic classification and outline generation in a fresh invocation."""
    if not session_id or not session_id.strip():
        raise ValueError("session_id is required for pipeline execution.")

    return await _execute(
        _FlowRequest(topic, session_id, audience, user_id, session_service, state_snapshot),
        span_name="pipeline_v2.start",
        error_event="pipeline_failed",
        build_runner=lambda svc: _build_runner(svc),
        build_message=_build_initial_message,
    )


async def run_pipeline_from_phase(
    *,
    phase: str,
    topic: str,
    audience: str = "general readers",
    user_id: str = "anonymous",
    session_id: str,
    session_service: Any | None = None,
    state_snapshot: dict[str, Any] | None = None,
) -> PipelineResult:
    """Start a new invocation at a lifecycle phase after outline review."""
    return await _execute(
        _FlowRequest(topic, session_id, audience, user_id, session_service, state_snapshot),
        span_name="pipeline_v2.resume_phase",
        error_event="pipeline_phase_resume_failed",
        span_attributes={"phase": phase},
        build_runner=lambda svc: _build_phase_runner(svc, phase),
        build_message=lambda _topic, _audience: _build_phase_message(phase, _topic, _audience),
    )


async def load_pipeline_result_from_state(
    *,
    topic: str,
    audience: str = "general readers",
    user_id: str = "anonymous",
    session_id: str,
    session_service: Any | None = None,
    state_snapshot: dict[str, Any] | None = None,
) -> PipelineResult:
    """Read a result back out of session state without running any model."""
    return await _execute(
        _FlowRequest(topic, session_id, audience, user_id, session_service, state_snapshot),
        span_name="pipeline_v2.load_state",
        error_event="pipeline_state_load_failed",
        build_runner=None,
    )


# Re-exported so callers can reason about the graph without importing
# src.workflows directly.
__all__ = [
    "APP",
    "APP_NAME",
    "EDITOR_REVIEW_KEY",
    "INTENT_RESULT_KEY",
    "OUTLINE_KEY",
    "CostInfo",
    "PipelineResult",
    "STAGE_BY_AUTHOR",
    "build_revision_workflow",
    "load_pipeline_result_from_state",
    "run_pipeline",
    "run_pipeline_from_phase",
]
