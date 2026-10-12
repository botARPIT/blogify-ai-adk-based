"""Failure handling.

Bad model output must fail loudly and specifically. The two ways that can go
wrong in opposite directions are equally bad: a validation failure swallowed
into empty state, or a handled error hidden from the worker.
"""

from __future__ import annotations

import pytest

import src.agents.pipeline as pipeline
from src.normalizer import NormalizationError
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
from tests.pipeline.test_pipeline_pause import _make_recording_service

TOPIC = "Testing workflow graphs"


@pytest.fixture
def scripted(monkeypatch):
    import src.agents.outline_review_agent as review_module

    def _apply(**overrides):
        defaults = {
            "intent": INTENT_OK,
            "outline": VALID_OUTLINE_MARKDOWN,
            "outline_review": "Outline approved.",
            "research": RESEARCH_OK,
            "writer": DRAFT,
            "editor": editor_review(approved=True),
        }
        defaults.update(overrides)
        installed = ScriptedModels(monkeypatch, **defaults)
        models = installed.__enter__()
        review = ScriptedLLM(replies=defaults["outline_review"])
        models["outline_review"] = review
        monkeypatch.setattr(review_module, "create_model", lambda _config: review)
        monkeypatch.setattr(pipeline, "APP", pipeline.build_app(build_fresh_generation_workflow()))
        return models

    return _apply


class TestNormalizationFailuresAreSurfaced:
    @pytest.mark.parametrize(
        ("stage", "role", "reply"),
        [
            ("outline", "outline", "Let me know what topic you'd like."),
            ("editor", "editor", "The draft reads well to me."),
            ("intent", "intent", "That looks like a good idea."),
        ],
    )
    async def test_unusable_output_is_reported_as_an_error(self, scripted, stage, role, reply):
        scripted(**{role: reply})
        result = await pipeline.run_pipeline(
            topic=TOPIC,
            session_id=f"fail-{stage}",
            session_service=_make_recording_service(),
        )

        assert result.error is not None
        assert f"stage={stage}" in result.error

    async def test_error_identifies_the_responsible_agent(self, scripted):
        scripted(outline="nonsense")
        result = await pipeline.run_pipeline(
            topic=TOPIC,
            session_id="fail-agent",
            session_service=_make_recording_service(),
        )

        assert "agent=outline_agent" in result.error

    async def test_error_names_the_detected_format(self, scripted):
        scripted(outline="prose, not json")
        result = await pipeline.run_pipeline(
            topic=TOPIC,
            session_id="fail-format",
            session_service=_make_recording_service(),
        )

        assert "format=markdown" in result.error

    async def test_empty_output_is_reported_distinctly(self, scripted):
        scripted(outline="")
        result = await pipeline.run_pipeline(
            topic=TOPIC,
            session_id="fail-empty",
            session_service=_make_recording_service(),
        )

        assert "format=empty" in result.error


class TestFailureDoesNotCorruptState:
    async def test_failed_run_reports_no_content(self, scripted):
        scripted(outline="nonsense")
        result = await pipeline.run_pipeline(
            topic=TOPIC,
            session_id="fail-state-1",
            session_service=_make_recording_service(),
        )

        assert result.final_content == ""
        assert result.paused_for_confirmation is False

    async def test_failed_run_does_not_reach_the_reviewer(self, scripted):
        """A reviewer must never be shown an outline that failed validation."""
        models = scripted(outline="nonsense")
        await pipeline.run_pipeline(
            topic=TOPIC,
            session_id="fail-state-2",
            session_service=_make_recording_service(),
        )

        assert models["outline_review"].call_count == 0
        assert models["research"].call_count == 0

    async def test_failed_run_produces_no_costs(self, scripted):
        scripted(outline="nonsense")
        result = await pipeline.run_pipeline(
            topic=TOPIC,
            session_id="fail-state-3",
            session_service=_make_recording_service(),
        )

        assert result.error is not None


class TestValidationErrorShape:
    def test_error_carries_structured_context(self):
        error = NormalizationError(
            workflow="w",
            stage="s",
            agent="a",
            reason="r",
            output_format="json",
            field_paths=["title", "sections.0.goal"],
        )
        message = str(error)
        for expected in ("workflow=w", "stage=s", "agent=a", "format=json", "reason=r"):
            assert expected in message
        assert "title,sections.0.goal" in message

    def test_error_is_a_value_error(self):
        """The worker catches Exception, and this stays catchable as one."""
        assert issubclass(NormalizationError, ValueError)


class TestExceptionsAreNotSwallowed:
    async def test_session_service_failure_reaches_the_result(self, scripted):
        scripted()

        class Broken:
            async def get_session(self, **_kwargs):
                raise RuntimeError("session store unavailable")

            async def create_session(self, **_kwargs):
                raise RuntimeError("session store unavailable")

        result = await pipeline.run_pipeline(
            topic=TOPIC, session_id="fail-store", session_service=Broken()
        )

        assert result.error is not None
        assert "session store unavailable" in result.error

    async def test_unknown_phase_is_reported_not_raised_to_the_caller(self, scripted):
        scripted()
        result = await pipeline.run_pipeline_from_phase(
            phase="writer_phase",
            topic=TOPIC,
            session_id="fail-phase",
            session_service=_make_recording_service(),
        )

        assert result.error is not None
        assert "Unsupported pipeline phase" in result.error
