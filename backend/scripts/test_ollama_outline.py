"""One-shot LiteLLM outline smoke test, bypassing Blogify's API and worker.

Run explicitly to compare Ollama/model latency with a queued generation:

    BLOGIFY_RUN_OLLAMA_OUTLINE_SMOKE=1 \
      .venv/bin/pytest -s scripts/test_ollama_outline.py

This diagnostic lives outside ``tests/`` so it does not alter the project's
15-unit / 3-integration / 2-E2E test portfolio count or run during normal CI.
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid

import pytest
from litellm import completion

from src.agents.outline_agent import OUTLINE_INSTRUCTION

# Load the same dev environment configuration as the API before importing the
# model catalog, which reads the provider settings from environment variables.
from src.config.env_config import config as _runtime_config  # noqa: F401
from src.llm.adapters.litellm import build_litellm_kwargs
from src.llm.config import LLMProvider, LLMTransport
from src.llm.model_configs import EDITOR_MODEL, OUTLINE_MODEL, RESEARCH_MODEL, WRITER_MODEL
from src.normalizer import normalize_outline
from src.workflows.state_schema import build_session_state

pytestmark = pytest.mark.integration


def test_ollama_outline_generation_without_worker() -> None:
    """Measure one real outline request directly through configured LiteLLM."""
    if os.getenv("BLOGIFY_RUN_OLLAMA_OUTLINE_SMOKE") != "1":
        pytest.skip("Set BLOGIFY_RUN_OLLAMA_OUTLINE_SMOKE=1 to call the configured LLM")
    if OUTLINE_MODEL.provider is not LLMProvider.OLLAMA:
        pytest.skip(f"Configured provider is {OUTLINE_MODEL.provider}; this diagnostic targets Ollama")
    if OUTLINE_MODEL.transport is not LLMTransport.OPENAI_COMPATIBLE:
        pytest.fail(f"Ollama model uses unsupported test transport: {OUTLINE_MODEL.transport}")

    intent = {
        "topic": "Doctor Doom's origin and rise to power",
        "audience": "Regular comic readers",
        "search_intent": "Understand the character's origin and motivations",
        "key_points": ["Victor von Doom", "Latveria", "rivalry with Reed Richards"],
    }
    prompt = OUTLINE_INSTRUCTION.replace("{intent_result}", json.dumps(intent))
    request = build_litellm_kwargs(OUTLINE_MODEL)
    request["num_retries"] = 0  # Measure one request, not retry/backoff time.
    request.update(
        messages=[{"role": "user", "content": prompt}],
        timeout=120,
    )

    started = time.perf_counter()
    response = completion(**request)
    elapsed_ms = round((time.perf_counter() - started) * 1000)

    raw_outline = response.choices[0].message.content or ""
    raw_outline = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw_outline.strip(), flags=re.IGNORECASE)
    outline = normalize_outline(raw_outline)
    usage = getattr(response, "usage", None)

    print(
        json.dumps(
            {
                "path": "direct_litellm_to_ollama",
                "model": request["model"],
                "api_base": OUTLINE_MODEL.api_base,
                "latency_ms": elapsed_ms,
                "prompt_tokens": getattr(usage, "prompt_tokens", None),
                "completion_tokens": getattr(usage, "completion_tokens", None),
                "outline_title": outline.title,
                "section_count": len(outline.sections),
            },
            indent=2,
        ),
        flush=True,
    )

    assert outline.title
    assert 3 <= len(outline.sections) <= 7


def test_post_outline_workflow_latency_without_worker(monkeypatch) -> None:
    """Time research, writing, and editing through the real ADK workflow.

    This bypasses Blogify's API, Redis dispatch, and worker while preserving the
    configured agents, prompts, LiteLLM calls, and Tavily research tool.
    """
    if os.getenv("BLOGIFY_RUN_OLLAMA_OUTLINE_SMOKE") != "1":
        pytest.skip("Set BLOGIFY_RUN_OLLAMA_OUTLINE_SMOKE=1 to call the configured LLM")
    models = (RESEARCH_MODEL, WRITER_MODEL, EDITOR_MODEL)
    if any(model.provider is not LLMProvider.OLLAMA for model in models):
        pytest.skip("This comparison requires all post-outline stages to use Ollama")
    if any(model.transport is not LLMTransport.OPENAI_COMPATIBLE for model in models):
        pytest.fail("All measured post-outline models must use the LiteLLM OpenAI-compatible transport")

    import asyncio

    from src.agents import research_agent as research_agent_module
    from src.agents.pipeline import run_pipeline_from_phase
    from src.tools.tavily_research import research_topic as real_research_topic

    tool_timings_ms: list[int] = []

    async def timed_research_topic(topic: str, max_results: int = 5):
        started = time.perf_counter()
        try:
            return await real_research_topic(topic=topic, max_results=max_results)
        finally:
            tool_timings_ms.append(round((time.perf_counter() - started) * 1000))

    monkeypatch.setattr(research_agent_module, "research_topic", timed_research_topic)

    topic = "Doctor Doom's origin and rise to power"
    audience = "Regular comic readers"
    outline = {
        "title": "Doctor Doom: From Victor von Doom to Ruler of Latveria",
        "sections": [
            {"id": "section_1", "heading": "Victor von Doom's Early Life", "goal": "Explain Doom's childhood and family history", "target_words": 180},
            {"id": "section_2", "heading": "The Experiment That Changed Everything", "goal": "Describe Doom's studies and accident", "target_words": 180},
            {"id": "section_3", "heading": "The Rise of Doctor Doom", "goal": "Cover Doom's armor, return, and rise to power", "target_words": 180},
            {"id": "section_4", "heading": "Ruler of Latveria and Rival to Reed Richards", "goal": "Explain Doom's rule and defining rivalry", "target_words": 180},
        ],
        "estimated_total_words": 720,
    }
    state_snapshot = build_session_state(
        topic=topic,
        audience=audience,
        intent_result={
            "topic": topic,
            "audience": audience,
            "key_points": ["Victor von Doom", "Latveria", "Reed Richards"],
        },
        blog_outline=outline,
        approved_outline=outline,
        outline_feedback=(
            "Keep the origin clear for readers new to the character and distinguish "
            "ambition from simple villainy."
        ),
    )
    session_id = f"diagnostic-post-outline-{uuid.uuid4()}"

    async def execute_workflow():
        return await run_pipeline_from_phase(
            phase="research_phase",
            topic=topic,
            audience=audience,
            user_id="diagnostic",
            session_id=session_id,
            state_snapshot=state_snapshot,
        )

    started = time.perf_counter()
    result = asyncio.run(execute_workflow())
    workflow_wall_ms = round((time.perf_counter() - started) * 1000)
    cost_by_stage = {cost.stage: cost for cost in result.costs}
    editor_review = result.editor_review if isinstance(result.editor_review, dict) else {}

    report = {
        "path": "direct_adk_post_outline_workflow_without_api_or_worker",
        "session_id": session_id,
        "models": {
            "research": RESEARCH_MODEL.name,
            "writer": WRITER_MODEL.name,
            "editor": EDITOR_MODEL.name,
        },
        "workflow_wall_ms": workflow_wall_ms,
        "stage_wall_ms": result.stage_timings_ms,
        "tavily_tool_ms": tool_timings_ms,
        "tokens_by_stage": {
            stage: cost_by_stage[stage].total_tokens for stage in cost_by_stage
        },
        "research_output_chars": len(str(result.research or "")),
        "draft_word_count": len(result.draft.split()),
        "editor_approved": editor_review.get("approved"),
        "error": result.error,
    }
    print(json.dumps(report, indent=2), flush=True)

    assert result.error is None, f"Post-outline workflow failed: {result.error}"
    assert result.draft.strip(), "Writer stage returned an empty draft"
    assert result.stage_timings_ms.get("research") is not None
    assert result.stage_timings_ms.get("writer") is not None
    assert result.stage_timings_ms.get("editor") is not None
    assert tool_timings_ms, "Research stage did not call the Tavily research tool"
