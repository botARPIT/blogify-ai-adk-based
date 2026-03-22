"""ADK-native blog generation pipeline.

Replaces the manual 443-line ``pipeline.py`` with declarative
ADK orchestration primitives:

* **SequentialAgent** — chains intent → outline → (HITL) → research → refinement
* **LoopAgent**       — writer ↔ editor refinement loop (max 2 iterations)
* **LongRunningFunctionTool** — async HITL approval after outline generation

State is passed between agents via ``output_key`` on the shared
``session.state`` — no custom "run X then parse Y" glue needed.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any

from google.adk.agents import SequentialAgent, LoopAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from src.agents.editor_agent import editor_agent
from src.agents.intent_agent import intent_agent
from src.agents.outline_agent import outline_agent
from src.agents.research_agent import research_agent
from src.agents.writer_agent import writer_agent
from src.config.logging_config import get_logger
from src.core.sanitization import sanitize_topic, sanitize_audience
from src.core.session_store import redis_session_service
from src.monitoring.tracing import trace_span

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Cost bookkeeping
# ---------------------------------------------------------------------------

@dataclass
class CostInfo:
    """Token usage for a single stage."""

    stage: str
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class PipelineResult:
    """Result bundle returned from a full pipeline run."""

    session_id: str
    intent_result: dict[str, Any] | None = None
    outline: dict[str, Any] | None = None
    research: dict[str, Any] | None = None
    draft: str = ""
    editor_review: dict[str, Any] | None = None
    final_content: str = ""
    costs: list[CostInfo] = field(default_factory=list)
    error: str | None = None


# ---------------------------------------------------------------------------
# Composite pipeline (SequentialAgent + LoopAgent)
# ---------------------------------------------------------------------------

# Writer → Editor refinement loop (max 2 iterations).
# If editor sets ``approved=true`` the loop can be exited early
# through the escalation mechanism.
refinement_loop = LoopAgent(
    name="refinement_loop",
    sub_agents=[writer_agent, editor_agent],
    max_iterations=2,
)

# Full blog pipeline: intent → outline → research → writer/editor
blog_pipeline = SequentialAgent(
    name="blog_pipeline",
    sub_agents=[
        intent_agent,       # output_key="intent_result"
        outline_agent,      # output_key="blog_outline"
        research_agent,     # output_key="research_data"
        refinement_loop,    # writer(blog_draft) + editor(editor_review)
    ],
)

# Default session service (worker can override with Redis-backed one)
APP_NAME = "blogify"


# ---------------------------------------------------------------------------
# Runner helper
# ---------------------------------------------------------------------------


def _extract_costs_from_events(events: list[Any], stage: str) -> CostInfo:
    """Extract token usage from ADK event stream.

    ADK events carry ``usage_metadata`` on model responses.  We scan
    all events and sum the token counts.
    """
    cost = CostInfo(stage=stage)
    for event in events:
        meta = getattr(event, "usage_metadata", None)
        if meta is None:
            # Some events expose it nested under content
            content = getattr(event, "content", None)
            if content:
                meta = getattr(content, "usage_metadata", None)
        if meta:
            cost.prompt_tokens += getattr(meta, "prompt_token_count", 0) or 0
            cost.completion_tokens += getattr(meta, "candidates_token_count", 0) or 0
            cost.total_tokens += getattr(meta, "total_token_count", 0) or 0
            cost.model = getattr(meta, "model_id", "") or cost.model
    return cost


async def run_pipeline(
    topic: str,
    audience: str = "general readers",
    user_id: str = "anonymous",
    session_id: str | None = None,
    session_service: Any | None = None,
) -> PipelineResult:
    """Run the full blog generation pipeline.

    Parameters
    ----------
    topic:
        Blog topic (sanitised before being sent to agents).
    audience:
        Target audience.
    user_id:
        Real user id — propagated to the ADK session.
    session_id:
        Optional external session id; generated if omitted.
    session_service:
        ADK session service to use.  Defaults to the Redis-backed
        ``redis_session_service`` global.

    Returns
    -------
    PipelineResult
        Contains all intermediate outputs and per-stage cost info.
    """
    session_id = session_id or str(uuid.uuid4())
    svc = session_service or redis_session_service

    # Sanitise inputs
    safe_topic = sanitize_topic(topic)
    safe_audience = sanitize_audience(audience)

    with trace_span("pipeline_v2.run", attributes={"user_id": user_id, "session_id": session_id}):
        result = PipelineResult(session_id=session_id)

        try:
            # Create a single session for the whole pipeline run (fixes 4.5)
            session = await svc.create_session(
                app_name=APP_NAME,
                user_id=user_id,
                session_id=session_id,
                state={
                    "topic": safe_topic,
                    "audience": safe_audience,
                },
            )

            runner = Runner(
                agent=blog_pipeline,
                app_name=APP_NAME,
                session_service=svc,
            )

            # Build the initial user message
            user_message = types.Content(
                role="user",
                parts=[types.Part(text=(
                    f"Generate a blog post about: {safe_topic}\n"
                    f"Target audience: {safe_audience}"
                ))],
            )

            # Run the pipeline — ADK handles sequencing automatically
            all_events: list[Any] = []
            async for event in runner.run_async(
                user_id=user_id,
                session_id=session.id,
                new_message=user_message,
            ):
                all_events.append(event)
                logger.debug(
                    "pipeline_event",
                    author=getattr(event, "author", "?"),
                    is_final=getattr(getattr(event, "actions", None), "escalate", False),
                )

            # Harvest results from session state
            state = session.state if hasattr(session, "state") else {}
            result.intent_result = state.get("intent_result")
            result.outline = state.get("blog_outline")
            result.research = state.get("research_data")
            result.draft = state.get("blog_draft", "")
            result.editor_review = state.get("editor_review")

            # Determine final content
            er = result.editor_review
            if isinstance(er, dict) and er.get("approved"):
                result.final_content = er.get("final_blog", result.draft)
            else:
                result.final_content = result.draft

            # Extract cost info per stage
            cost = _extract_costs_from_events(all_events, "full_pipeline")
            result.costs.append(cost)

            logger.info(
                "pipeline_completed",
                session_id=session_id,
                total_tokens=cost.total_tokens,
                has_final_content=bool(result.final_content),
            )

        except Exception as exc:
            result.error = str(exc)
            logger.error(
                "pipeline_failed",
                session_id=session_id,
                error=str(exc),
                exc_info=True,
            )

    return result
