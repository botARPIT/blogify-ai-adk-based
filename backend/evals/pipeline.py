"""Execute one golden against the production ADK graph definitions."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Any
from unittest.mock import patch

from google.adk.sessions import InMemorySessionService
from google.adk.tools.tool_context import ToolContext

import src.agents.research_agent as research_agent_module
from evals.dataset import GoldenCase
from src.core.workflow_state_keys import RESEARCH_TOOL_DATA_KEY
from src.models.orm_models import BlogJobPhase
from src.workflows.contracts import WorkflowRunRequest, WorkflowRunResult
from src.workflows.runner import WorkflowRunner
from src.workflows.state_schema import build_session_state


@dataclass(slots=True)
class PipelineExecution:
    """Relevant output and ADK events from one golden's workflow run."""

    result: WorkflowRunResult
    events: list[Any]


def tool_calls_from_events(events: list[Any]) -> list[dict[str, Any]]:
    """Project ADK function-call events into DeepEval-compatible tool data."""
    calls: list[dict[str, Any]] = []
    for event in events:
        get_calls = getattr(event, "get_function_calls", None)
        if not callable(get_calls):
            continue
        for call in get_calls() or []:
            calls.append(
                {
                    "name": str(getattr(call, "name", "")),
                    "input_parameters": dict(getattr(call, "args", {}) or {}),
                }
            )
    return calls


async def run_case(case: GoldenCase) -> PipelineExecution:
    """Run the fresh-generation gate and, when allowed, the post-outline graph.

    Search output is fixed to the golden's evidence payload. Model generation
    and tool selection remain real; external search variance is removed.
    """
    session_id = f"eval-{case.id}-{uuid.uuid4().hex}"
    user_id = "deepeval-user"
    session_service = InMemorySessionService()
    runner = WorkflowRunner(session_service_factory=lambda: session_service)
    events: list[Any] = []
    collect_events = runner._collect_events

    async def capture_events(**kwargs: Any) -> list[Any]:
        collected = await collect_events(**kwargs)
        events.extend(collected)
        return collected

    runner._collect_events = capture_events  # type: ignore[method-assign]
    active_payload: dict[str, Any] = {}

    async def fixed_research_topic(
        topic: str,
        max_results: int = 5,
        tool_context: ToolContext | None = None,
    ) -> dict[str, Any]:
        del max_results
        payload = dict(active_payload)
        payload["topic"] = topic
        if tool_context is not None:
            tool_context.state[RESEARCH_TOOL_DATA_KEY] = payload
        return payload

    with patch.object(research_agent_module, "research_topic", fixed_research_topic):
        outline_result = await runner.run(
            WorkflowRunRequest(
                phase=BlogJobPhase.FRESH_GENERATION,
                adk_session_id=session_id,
                user_id=user_id,
                topic=case.topic,
                audience=case.audience,
                tone=case.tone,
            )
        )
        if outline_result.error:
            raise RuntimeError(f"{case.id}: fresh-generation phase failed: {outline_result.error}")

        if case.kind == "blocked":
            if outline_result.intent_result != {"intent_clear": case.expected_intent_clear}:
                raise AssertionError(
                    f"{case.id}: expected intent_clear={case.expected_intent_clear}, "
                    f"got {outline_result.intent_result}"
                )
            if outline_result.outline:
                raise AssertionError(f"{case.id}: blocked input unexpectedly generated an outline")
            if tool_calls_from_events(events):
                raise AssertionError(f"{case.id}: blocked input unexpectedly called a tool")
            return PipelineExecution(result=outline_result, events=events)

        if outline_result.intent_result != {"intent_clear": True}:
            raise AssertionError(f"{case.id}: valid input was blocked: {outline_result.intent_result}")
        if not outline_result.outline or not outline_result.outline.get("sections"):
            raise AssertionError(f"{case.id}: no valid outline was produced")

        active_payload.update(case.research or {})
        snapshot = build_session_state(
            topic=case.topic,
            audience=case.audience,
            tone=case.tone,
            intent_result=outline_result.intent_result,
            blog_outline=outline_result.outline,
            approved_outline=outline_result.outline,
        )
        result = await runner.run(
            WorkflowRunRequest(
                phase=BlogJobPhase.RESEARCH_PHASE,
                adk_session_id=session_id,
                user_id=user_id,
                topic=case.topic,
                audience=case.audience,
                tone=case.tone,
                state_snapshot=snapshot,
            )
        )
        if result.error:
            raise RuntimeError(f"{case.id}: post-outline phase failed: {result.error}")
        if not result.research or not result.research.get("sources"):
            raise AssertionError(f"{case.id}: workflow completed without validated research")
        if not result.final_content.strip():
            raise AssertionError(f"{case.id}: workflow produced no final content")
        source_count = len(result.research["sources"])
        cited_indexes = [
            int(value) for value in re.findall(r"\[(\d{1,2})\]", result.final_content)
        ]
        if not cited_indexes or any(index < 1 or index > source_count for index in cited_indexes):
            raise AssertionError(f"{case.id}: final blog has missing or invalid source citations")
        return PipelineExecution(result=result, events=events)
