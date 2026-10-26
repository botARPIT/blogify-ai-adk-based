"""ADK runtime adapter for one durable blog workflow segment."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from google.adk.events import Event, EventActions
from google.adk.sessions import InMemorySessionService
from google.genai import types

from src.agents.timing import AGENT_TIMINGS_STATE_KEY
from src.config.budget_config import get_model_cost
from src.config.logging_config import get_logger
from src.core.sanitization import sanitize_audience, sanitize_tone, sanitize_topic
from src.models.orm_models import BlogJobPhase
from src.monitoring.metrics import agent_cost_usd, agent_token_usage
from src.monitoring.tracing import trace_span
from src.workflows.common import APP_NAME, build_app, build_runner
from src.workflows.contracts import StageUsage, WorkflowRunRequest, WorkflowRunResult
from src.workflows.registry import get_workflow_spec
from src.workflows.state_schema import empty_session_state, missing_session_state_keys

logger = get_logger(__name__)

STAGE_BY_AUTHOR = {
    "intent_classifier": "intent",
    "outline_agent": "outline",
    "research_agent": "research",
    "writer_agent": "writer",
    "editor_agent": "editor",
}


class WorkflowRunner:
    """Run ADK graphs without knowing anything about database lifecycle state."""

    def __init__(
        self,
        session_service_factory: Callable[[], Any] = InMemorySessionService,
    ) -> None:
        self._session_service_factory = session_service_factory

    async def run(self, request: WorkflowRunRequest) -> WorkflowRunResult:
        """Execute the graph registered for ``request.phase`` and normalize its output."""
        result = WorkflowRunResult(adk_session_id=request.adk_session_id)
        attributes = {
            "user_id": request.user_id,
            "session_id": request.adk_session_id,
            "phase": request.phase.value,
        }

        with trace_span("workflow.run", attributes=attributes):
            try:
                topic_is_valid, safe_topic, topic_error = sanitize_topic(request.topic)
                if not topic_is_valid:
                    raise ValueError(topic_error or "Invalid blog topic")
                safe_audience = sanitize_audience(request.audience)
                safe_tone = sanitize_tone(request.tone)
                service = self._session_service_factory()

                await self._ensure_session(
                    service=service,
                    request=request,
                    topic=safe_topic,
                    audience=safe_audience,
                    tone=safe_tone,
                )

                spec = get_workflow_spec(request.phase)
                app = build_app(spec.builder())
                runner = build_runner(app, service)
                events = await self._collect_events(
                    runner=runner,
                    request=request,
                    message=self._build_message(
                        phase=request.phase,
                        prompt_label=spec.prompt_label,
                        topic=safe_topic,
                        audience=safe_audience,
                        tone=safe_tone,
                    ),
                )
                await self._populate_result(
                    service=service,
                    request=request,
                    result=result,
                    events=events,
                )
            except Exception as exc:
                result.error = str(exc)
                result.retryable = _is_transient_downstream_error(exc)
                logger.error(
                    "workflow_run_failed",
                    session_id=request.adk_session_id,
                    phase=request.phase.value,
                    error=str(exc),
                    exc_info=True,
                )

        return result

    async def _ensure_session(
        self,
        *,
        service: Any,
        request: WorkflowRunRequest,
        topic: str,
        audience: str,
        tone: str,
    ) -> Any:
        existing = await service.get_session(
            app_name=APP_NAME,
            user_id=request.user_id,
            session_id=request.adk_session_id,
        )
        defaults = empty_session_state(topic, audience, tone)
        snapshot = dict(request.state_snapshot)

        if existing is None:
            defaults.update(snapshot)
            return await service.create_session(
                app_name=APP_NAME,
                user_id=request.user_id,
                session_id=request.adk_session_id,
                state=defaults,
            )

        delta = snapshot
        for key in missing_session_state_keys({**existing.state, **delta}):
            delta[key] = defaults[key]
        if delta:
            await service.append_event(
                existing,
                Event(
                    author="workflow_snapshot",
                    actions=EventActions(state_delta=delta),
                ),
            )
        return existing

    async def _collect_events(
        self,
        *,
        runner: Any,
        request: WorkflowRunRequest,
        message: types.Content,
    ) -> list[Any]:
        events: list[Any] = []
        async for event in runner.run_async(
            user_id=request.user_id,
            session_id=request.adk_session_id,
            new_message=message,
        ):
            events.append(event)
            logger.debug(
                "workflow_event",
                phase=request.phase.value,
                author=getattr(event, "author", "?"),
            )
        return events

    async def _populate_result(
        self,
        *,
        service: Any,
        request: WorkflowRunRequest,
        result: WorkflowRunResult,
        events: list[Any],
    ) -> None:
        session = await service.get_session(
            app_name=APP_NAME,
            user_id=request.user_id,
            session_id=request.adk_session_id,
        )
        state = session.state if session and hasattr(session, "state") else {}
        result.intent_result = _dict_or_empty(state.get("intent_result"))
        result.outline = _dict_or_empty(state.get("blog_outline"))
        result.research = _dict_or_empty(state.get("research_data"))
        result.draft = str(state.get("blog_draft") or "")
        result.editor_review = _dict_or_empty(state.get("editor_review"))

        review = result.editor_review or {}
        result.final_content = str(review.get("final_blog") or result.draft)

        timings = state.get(AGENT_TIMINGS_STATE_KEY, {})
        if isinstance(timings, dict):
            result.stage_timings_ms = {
                str(stage): max(0, int(duration))
                for stage, duration in timings.items()
                if isinstance(duration, (int, float))
            }

        result.usage = _extract_usage(events, result.stage_timings_ms)
        for usage in result.usage:
            if usage.total_tokens > 0:
                agent_token_usage.labels(agent_name=usage.stage).observe(
                    usage.total_tokens
                )
                agent_cost_usd.labels(agent_name=usage.stage).observe(
                    get_model_cost(usage.model, usage.total_tokens)
                )
        logger.info(
            "workflow_completed",
            session_id=request.adk_session_id,
            phase=request.phase.value,
            total_tokens=sum(item.total_tokens for item in result.usage),
            has_final_content=bool(result.final_content),
        )

    @staticmethod
    def _build_message(
        *,
        phase: BlogJobPhase,
        prompt_label: str,
        topic: str,
        audience: str,
        tone: str,
    ) -> types.Content:
        return types.Content(
            role="user",
            parts=[
                types.Part(
                    text=(
                        f"{prompt_label}.\n"
                        f"Workflow phase: {phase.value}\n"
                        f"Topic: {topic}\n"
                        f"Target audience: {audience}\n"
                        f"Requested tone: {tone}"
                    )
                )
            ],
        )


def _dict_or_empty(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _usage_metadata(event: Any) -> tuple[str | None, Any | None]:
    author = getattr(event, "author", None)
    metadata = getattr(event, "usage_metadata", None)
    if metadata is None:
        content = getattr(event, "content", None)
        metadata = getattr(content, "usage_metadata", None) if content else None
    return author, metadata


def _extract_usage(
    events: list[Any],
    stage_timings_ms: dict[str, int],
) -> list[StageUsage]:
    usage_by_stage: dict[str, StageUsage] = {}
    for event in events:
        author, metadata = _usage_metadata(event)
        if metadata is None:
            continue
        stage = STAGE_BY_AUTHOR.get(author or "")
        if stage is None:
            continue
        usage = usage_by_stage.setdefault(stage, StageUsage(stage=stage))
        usage.prompt_tokens += getattr(metadata, "prompt_token_count", 0) or 0
        usage.completion_tokens += getattr(metadata, "candidates_token_count", 0) or 0
        usage.total_tokens += getattr(metadata, "total_token_count", 0) or 0
        usage.model = getattr(metadata, "model_id", "") or usage.model

    ordered = ["intent", "outline", "research", "writer", "editor"]
    usage_items = [usage_by_stage[stage] for stage in ordered if stage in usage_by_stage]
    if not usage_items:
        fallback = StageUsage(stage="full_workflow")
        for event in events:
            _, metadata = _usage_metadata(event)
            if metadata is None:
                continue
            fallback.prompt_tokens += getattr(metadata, "prompt_token_count", 0) or 0
            fallback.completion_tokens += getattr(metadata, "candidates_token_count", 0) or 0
            fallback.total_tokens += getattr(metadata, "total_token_count", 0) or 0
            fallback.model = getattr(metadata, "model_id", "") or fallback.model
        if fallback.total_tokens:
            usage_items.append(fallback)

    recorded = {item.stage for item in usage_items}
    for item in usage_items:
        item.latency_ms = stage_timings_ms.get(item.stage)
    for stage, duration_ms in stage_timings_ms.items():
        if stage not in recorded:
            usage_items.append(StageUsage(stage=stage, latency_ms=duration_ms))
    return usage_items


def _is_transient_downstream_error(exc: Exception) -> bool:
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
        raw_status_code = getattr(current, "status_code", None) or getattr(current, "code", None)
        try:
            status_code: int | None = int(raw_status_code) if raw_status_code is not None else None
        except (TypeError, ValueError):
            status_code = None
        if status_code == 429 or (isinstance(status_code, int) and 500 <= status_code < 600):
            return True
        current = current.__cause__ or current.__context__
    return False


__all__ = ["STAGE_BY_AUTHOR", "WorkflowRunner"]
