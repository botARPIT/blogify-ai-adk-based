"""Fresh generation end to end, without a provider.

Drives ``run_pipeline`` against a scripted model and an in-memory session
service. Asserts the contract the worker depends on: what lands in state, what
``PipelineResult`` carries, and that the outline review still pauses.
"""

from __future__ import annotations

import pytest

import src.agents.pipeline as pipeline
from src.workflows.fresh_generation import build_fresh_generation_workflow
from tests.fakes.scripted_llm import (
    DRAFT,
    INTENT_OK,
    RESEARCH_OK,
    VALID_OUTLINE_MARKDOWN,
    ScriptedLLM,
    ScriptedModels,
    editor_review,
)

TOPIC = "Testing workflow graphs"


def _make_recording_service():
    """An in-memory session service that records the pipeline's session calls.

    Subclasses ADK's own service so the pipeline runs against the same contract
    it sees in production — only the storage is swapped out.
    """
    from google.adk.sessions.in_memory_session_service import InMemorySessionService

    class RecordingSessionService(InMemorySessionService):
        def __init__(self):
            super().__init__()
            self.created: list[tuple] = []

        async def create_session(self, *, app_name, user_id, session_id, state):
            self.created.append((app_name, user_id, session_id, dict(state or {})))
            return await super().create_session(
                app_name=app_name,
                user_id=user_id,
                session_id=session_id,
                state=state,
            )

    return RecordingSessionService()


@pytest.fixture
def scripted(monkeypatch):
    """Bind scripted models to every agent and rebuild the pipeline's App.

    ``run_pipeline`` executes a module-level ``App`` built at import time, so
    swapping a model's constructor alone would not reach it. Rebuilding under
    the patch is what makes these tests exercise the real entrypoint while
    keeping the model deterministic. Returns the role -> model mapping so a
    test can assert how often each stage ran.
    """
    import src.agents.outline_review_agent as review_module

    def _apply(review_model=None, **overrides):
        defaults = {
            "intent": INTENT_OK,
            "outline": VALID_OUTLINE_MARKDOWN,
            "outline_review": "Outline approved.",
            "research": RESEARCH_OK,
            "writer": DRAFT,
            "editor": editor_review(approved=True),
        }
        defaults.update(overrides)

        review = (
            review_model
            if review_model is not None
            else ScriptedLLM(replies=defaults["outline_review"])
        )
        plain = {key: value for key, value in defaults.items() if key != "outline_review"}
        installed = ScriptedModels(monkeypatch, **plain)
        models = installed.__enter__()
        models["outline_review"] = review
        monkeypatch.setattr(review_module, "create_model", lambda _config: review)

        # Build the App only after every model constructor is patched, so the
        # graph is assembled from the scripted models rather than real ones.
        monkeypatch.setattr(pipeline, "APP", pipeline.build_app(build_fresh_generation_workflow()))
        return models

    return _apply


class TestFreshGeneration:
    async def test_runs_every_stage_and_returns_content(self, scripted):
        scripted()
        service = _make_recording_service()
        result = await pipeline.run_pipeline(
            topic=TOPIC,
            session_id="sess-1",
            session_service=service,
        )

        assert result.error is None
        assert result.intent_result["status"] == "CLEAR"
        assert result.outline["title"] == "Test Blog"
        assert result.draft
        assert result.editor_review["approved"] is True
        assert result.final_content

    async def test_seeds_the_session_with_context_for_the_agents(self, scripted):
        scripted()
        service = _make_recording_service()
        await pipeline.run_pipeline(topic=TOPIC, session_id="sess-2", session_service=service)

        app_name, _user_id, session_id, state = service.created[0]
        assert app_name == pipeline.APP_NAME
        # sanitize_topic returns (is_valid, sanitized_value, error).
        assert state["topic"][0] is True
        assert state["topic"][1] == TOPIC
        assert "blog_outline" in state

    async def test_seeds_the_session_with_a_state_snapshot(self, scripted):
        scripted()
        service = _make_recording_service()
        await pipeline.run_pipeline(
            topic=TOPIC,
            session_id="sess-3",
            session_service=service,
            state_snapshot={"blog_outline": {"title": "Preloaded"}},
        )

        _app_name, _user_id, _session_id, state = service.created[0]
        assert state["blog_outline"] == {"title": "Preloaded"}

    async def test_costs_are_reported_per_stage(self, scripted):
        scripted()
        service = _make_recording_service()
        result = await pipeline.run_pipeline(
            topic=TOPIC, session_id="sess-4", session_service=service
        )

        stages = [cost.stage for cost in result.costs]
        assert "intent" in stages
        assert "outline" in stages
        assert sum(cost.total_tokens for cost in result.costs) > 0

    async def test_topic_is_sanitized_before_reaching_the_model(self, scripted):
        scripted()
        service = _make_recording_service()
        await pipeline.run_pipeline(
            topic=f"  <script>alert(1)</script> {TOPIC}  ",
            session_id="sess-5",
            session_service=service,
        )

        _app, _user, _session, state = service.created[0]
        assert "<script>" not in state["topic"]


class TestOutlineReviewPause:
    async def test_review_pauses_before_research(self, scripted):
        from tests.fakes.scripted_llm import ScriptedConfirmationLLM

        scripted(review_model=ScriptedConfirmationLLM())
        service = _make_recording_service()
        result = await pipeline.run_pipeline(
            topic=TOPIC, session_id="sess-6", session_service=service
        )

        assert result.paused_for_confirmation is True
        assert result.invocation_id
        assert result.confirmation_request_id
        assert result.confirmation_payload["outline"]["title"] == "Test Blog"

    async def test_paused_run_still_exposes_the_validated_outline(self, scripted):
        """The worker persists this outline and shows it to the reviewer, so it
        must already be a valid OutlineSchema at the pause."""
        from tests.fakes.scripted_llm import ScriptedConfirmationLLM

        scripted(review_model=ScriptedConfirmationLLM())
        service = _make_recording_service()
        result = await pipeline.run_pipeline(
            topic=TOPIC, session_id="sess-7", session_service=service
        )

        assert result.outline["title"] == "Test Blog"
        assert len(result.outline["sections"]) == 3
        assert result.draft == ""

    async def test_review_does_not_run_research_or_writer(self, scripted):
        from tests.fakes.scripted_llm import ScriptedConfirmationLLM

        models = scripted(review_model=ScriptedConfirmationLLM())
        service = _make_recording_service()
        await pipeline.run_pipeline(topic=TOPIC, session_id="sess-8", session_service=service)

        assert models["research"].call_count == 0
        assert models["writer"].call_count == 0
