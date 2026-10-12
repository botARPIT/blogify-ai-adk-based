from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from google.adk.agents import Agent
from google.adk.apps import App
from google.adk.runners import Runner
from google.genai import types

import src.agents.editor_agent as editor_module
from src.core.session_store import redis_session_service
from tests.fakes.fake_llm import FakeLLM, load_scenario

FIXTURE_ROOT = Path(__file__).parents[1] / "fixtures" / "llm"
SCENARIO_PATH = FIXTURE_ROOT / "scenarios" / "editor_approved.json"


@pytest.mark.asyncio
async def test_editor_agent_uses_deterministic_fake_llm_and_persists_events(monkeypatch):
    scenario = load_scenario(SCENARIO_PATH)

    def fake_model(_config=None):
        return FakeLLM(
            stage="editor",
            scenario=scenario,
            fixture_root=FIXTURE_ROOT,
        )

    # Keep the production agent definition and its raw output contract. Only the
    # model is replaced: the agent still builds its model through the factory.
    monkeypatch.setattr(editor_module, "create_model", fake_model)

    agent: Agent = editor_module.create_editor_agent()
    app = App(name="blogify-test", root_agent=agent)
    runner = Runner(
        app=app,
        app_name="blogify-test",
        session_service=redis_session_service,
    )

    session_id = f"test-editor-{uuid.uuid4()}"
    user_id = "fake-user"
    await redis_session_service.create_session(
        app_name="blogify-test",
        user_id=user_id,
        session_id=session_id,
        state={
            "blog_draft": "A deterministic draft for the editor.",
            "research_data": {"sources": [{"title": "Synthetic source"}]},
        },
    )

    events = []
    async for event in runner.run_async(
        user_id=user_id,
        session_id=session_id,
        new_message=types.Content(
            role="user",
            parts=[types.Part(text="Review the supplied draft.")],
        ),
    ):
        events.append(event)

    session = await redis_session_service.get_session(
        app_name="blogify-test",
        user_id=user_id,
        session_id=session_id,
    )
    assert session is not None
    assert events
    assert len(session.events) >= 2

    serialized = session.model_dump(mode="json")
    assert any(
        part.get("thought") is True
        for event in serialized["events"]
        for part in ((event.get("content") or {}).get("parts") or [])
    )
    # The agent no longer relies on ADK enforcing EditorReviewSchema, so the
    # typed value is produced by the deterministic workflow node. What the
    # agent owes the pipeline is raw, faithful model output.
    raw = session.state.get("editor_review_raw")
    assert isinstance(raw, str) and raw.strip()
    assert json.loads(raw)["approved"] is True
