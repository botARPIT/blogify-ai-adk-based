"""ADK-native blog pipeline with a resumable outline review gate."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from google.adk.agents import Agent, LoopAgent, SequentialAgent
from google.adk.apps.app import App, ResumabilityConfig
from google.adk.runners import Runner
from google.adk.tools import ToolContext
from google.genai import types

from src.agents.editor_agent import editor_agent
from src.agents.intent_agent import intent_agent
from src.agents.outline_agent import outline_agent
from src.agents.research_agent import research_agent
from src.agents.writer_agent import writer_agent
from src.config import OUTLINE_MODEL, create_retry_config
from src.config.logging_config import get_logger
from src.core.sanitization import sanitize_audience, sanitize_topic
from src.core.session_store import redis_session_service
from src.models.schemas import OutlineSchema
from src.monitoring.tracing import trace_span

logger = get_logger(__name__)

REQUEST_CONFIRMATION_FUNCTION_CALL_NAME = "adk_request_confirmation"


@dataclass
class CostInfo:
    stage: str
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


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
    paused_for_confirmation: bool = False
    invocation_id: str | None = None
    confirmation_request_id: str | None = None
    confirmation_payload: dict[str, Any] | None = None


async def review_generated_outline(tool_context: ToolContext) -> dict[str, Any]:
    """Pause the pipeline so a human can approve or edit the generated outline."""
    current_outline = tool_context.state.get("blog_outline") or {}
    validated_outline = OutlineSchema.model_validate(current_outline).model_dump()

    if not tool_context.tool_confirmation:
        payload = {
            "topic": tool_context.state.get("topic"),
            "audience": tool_context.state.get("audience"),
            "outline": validated_outline,
            "instructions": (
                "Review the outline. You can edit the outline and add guidance "
                "for what data, evidence, or emphasis should appear in the final blog."
            ),
            "response_schema": {
                "approved_outline": "OutlineSchema",
                "feedback_text": "Optional string",
            },
        }
        tool_context.request_confirmation(
            hint="Review and approve the generated outline before final drafting continues.",
            payload=payload,
        )
        tool_context.actions.skip_summarization = True
        return {
            "status": "awaiting_outline_review",
            "outline": validated_outline,
        }

    if not tool_context.tool_confirmation.confirmed:
        return {"error": "Outline review was rejected by the user."}

    confirmation_payload = tool_context.tool_confirmation.payload or {}
    approved_outline = confirmation_payload.get("approved_outline") or validated_outline
    approved_outline = OutlineSchema.model_validate(approved_outline).model_dump()
    feedback_text = str(confirmation_payload.get("feedback_text") or "").strip()

    tool_context.state["blog_outline"] = approved_outline
    tool_context.state["approved_outline"] = approved_outline
    tool_context.state["outline_feedback"] = feedback_text

    return {
        "status": "outline_approved",
        "approved_outline": approved_outline,
        "feedback_text": feedback_text,
    }


outline_review_agent = Agent(
    name="outline_review_agent",
    model=writer_agent.model,
    instruction=(
        "You are only an outline approval checkpoint. "
        "The generated outline is in {blog_outline}. "
        "If outline_review_result is empty, you must call the review_generated_outline "
        "tool exactly once so a human can approve or edit the outline. "
        "After the tool responds with status='awaiting_outline_review', stop immediately. "
        "After the tool responds with status='outline_approved', respond with a single short "
        "handoff sentence confirming the outline is approved. "
        "Do not perform research. Do not write content. Do not call any tool other than "
        "review_generated_outline. Never call web_search, research_sections, "
        "generate_blog_post_section, or any other tool."
    ),
    tools=[review_generated_outline],
    output_key="outline_review_result",
)


refinement_loop = LoopAgent(
    name="refinement_loop",
    sub_agents=[writer_agent, editor_agent],
    max_iterations=2,
)

blog_pipeline = SequentialAgent(
    name="blog_pipeline",
    sub_agents=[
        intent_agent,
        outline_agent,
        outline_review_agent,
        research_agent,
        refinement_loop,
    ],
)

APP_NAME = "blogify"
APP = App(
    name=APP_NAME,
    root_agent=blog_pipeline,
    resumability_config=ResumabilityConfig(is_resumable=True),
)

STAGE_BY_AUTHOR = {
    "intent_classifier": "intent",
    "outline_agent": "outline",
    "research_agent": "research",
    "writer_agent": "writer",
    "editor_agent": "editor",
}


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


def _initial_state(topic: str, audience: str) -> dict[str, Any]:
    return {
        "topic": topic,
        "audience": audience,
        "intent_result": {},
        "blog_outline": {},
        "approved_outline": {},
        "outline_feedback": "",
        "outline_review_result": {},
        "research_data": {},
        "blog_draft": "",
        "editor_review": {},
    }


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


async def _ensure_session(
    *,
    svc: Any,
    session_id: str,
    user_id: str,
    safe_topic: str,
    safe_audience: str,
) -> Any:
    session = await svc.get_session(
        app_name=APP_NAME,
        user_id=user_id,
        session_id=session_id,
    )
    if session is not None:
        return session

    return await svc.create_session(
        app_name=APP_NAME,
        user_id=user_id,
        session_id=session_id,
        state=_initial_state(safe_topic, safe_audience),
    )


def _build_runner(session_service: Any) -> Runner:
    return Runner(
        app=APP,
        app_name=APP_NAME,
        session_service=session_service,
    )


def _build_initial_message(topic: str, audience: str) -> types.Content:
    return types.Content(
        role="user",
        parts=[types.Part(text=(
            f"Generate a blog post about: {topic}\n"
            f"Target audience: {audience}"
        ))],
    )


def _build_confirmation_message(
    *,
    confirmation_request_id: str,
    approved_outline: dict[str, Any],
    feedback_text: str | None,
) -> types.Content:
    return types.Content(
        role="user",
        parts=[types.Part(function_response=types.FunctionResponse(
            id=confirmation_request_id,
            name=REQUEST_CONFIRMATION_FUNCTION_CALL_NAME,
            response={
                "confirmed": True,
                "payload": {
                    "approved_outline": approved_outline,
                    "feedback_text": feedback_text or "",
                },
            },
        ))],
    )


def _extract_pause_metadata(events: list[Any]) -> tuple[bool, str | None, str | None, dict[str, Any] | None]:
    for event in reversed(events):
        function_calls = getattr(event, "get_function_calls", lambda: [])()
        for function_call in function_calls:
            if function_call.name != REQUEST_CONFIRMATION_FUNCTION_CALL_NAME:
                continue
            payload = None
            args = getattr(function_call, "args", {}) or {}
            tool_confirmation = args.get("toolConfirmation") or {}
            if isinstance(tool_confirmation, dict):
                payload = tool_confirmation.get("payload")
            return True, getattr(event, "invocation_id", None), function_call.id, payload
    return False, None, None, None


async def _run_runner(
    *,
    runner: Runner,
    user_id: str,
    session_id: str,
    new_message: types.Content | None,
    invocation_id: str | None = None,
) -> list[Any]:
    events: list[Any] = []
    async for event in runner.run_async(
        user_id=user_id,
        session_id=session_id,
        invocation_id=invocation_id,
        new_message=new_message,
    ):
        events.append(event)
        logger.debug(
            "pipeline_event",
            author=getattr(event, "author", "?"),
            invocation_id=getattr(event, "invocation_id", None),
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
    (
        result.paused_for_confirmation,
        result.invocation_id,
        result.confirmation_request_id,
        result.confirmation_payload,
    ) = _extract_pause_metadata(events)

    logger.info(
        "pipeline_completed",
        session_id=session_id,
        total_tokens=sum(cost.total_tokens for cost in result.costs),
        paused_for_confirmation=result.paused_for_confirmation,
        has_final_content=bool(result.final_content),
    )
    return result


async def run_pipeline(
    topic: str,
    audience: str = "general readers",
    user_id: str = "anonymous",
    session_id: str | None = None,
    session_service: Any | None = None,
) -> PipelineResult:
    session_id = session_id or str(uuid.uuid4())
    svc = session_service or redis_session_service
    safe_topic = sanitize_topic(topic)
    safe_audience = sanitize_audience(audience)
    result = PipelineResult(session_id=session_id)

    with trace_span("pipeline_v2.start", attributes={"user_id": user_id, "session_id": session_id}):
        try:
            await _ensure_session(
                svc=svc,
                session_id=session_id,
                user_id=user_id,
                safe_topic=safe_topic,
                safe_audience=safe_audience,
            )
            runner = _build_runner(svc)
            events = await _run_runner(
                runner=runner,
                user_id=user_id,
                session_id=session_id,
                new_message=_build_initial_message(safe_topic, safe_audience),
            )
            return await _finalize_result(
                svc=svc,
                result=result,
                user_id=user_id,
                session_id=session_id,
                events=events,
            )
        except Exception as exc:
            result.error = str(exc)
            logger.error("pipeline_failed", session_id=session_id, error=str(exc), exc_info=True)
            return result


async def resume_pipeline(
    *,
    topic: str,
    audience: str = "general readers",
    user_id: str = "anonymous",
    session_id: str,
    invocation_id: str,
    confirmation_request_id: str,
    approved_outline: dict[str, Any],
    feedback_text: str | None = None,
    session_service: Any | None = None,
) -> PipelineResult:
    svc = session_service or redis_session_service
    safe_topic = sanitize_topic(topic)
    safe_audience = sanitize_audience(audience)
    result = PipelineResult(session_id=session_id)

    with trace_span("pipeline_v2.resume", attributes={"user_id": user_id, "session_id": session_id}):
        try:
            await _ensure_session(
                svc=svc,
                session_id=session_id,
                user_id=user_id,
                safe_topic=safe_topic,
                safe_audience=safe_audience,
            )
            runner = _build_runner(svc)
            events = await _run_runner(
                runner=runner,
                user_id=user_id,
                session_id=session_id,
                invocation_id=invocation_id,
                new_message=_build_confirmation_message(
                    confirmation_request_id=confirmation_request_id,
                    approved_outline=OutlineSchema.model_validate(approved_outline).model_dump(),
                    feedback_text=feedback_text,
                ),
            )
            return await _finalize_result(
                svc=svc,
                result=result,
                user_id=user_id,
                session_id=session_id,
                events=events,
            )
        except Exception as exc:
            result.error = str(exc)
            logger.error("pipeline_resume_failed", session_id=session_id, error=str(exc), exc_info=True)
            return result
