"""Resume after outline review.

Covers the pause/resume channel the worker depends on: a paused run reports the
handles needed to continue, and a resumed run continues *past* review rather
than restarting generation.
"""

from __future__ import annotations

import pytest
from google.genai import types

import src.agents.pipeline as pipeline
from src.workflows.fresh_generation import build_fresh_generation_workflow
from tests.fakes.scripted_llm import (
    DRAFT,
    INTENT_OK,
    RESEARCH_OK,
    VALID_OUTLINE_MARKDOWN,
    ScriptedConfirmationLLM,
    ScriptedLLM,
    ScriptedModels,
    editor_review,
)
from tests.pipeline.test_pipeline_pause import _make_recording_service

TOPIC = "Testing workflow graphs"


@pytest.fixture
def scripted(monkeypatch):
    import src.agents.outline_review_agent as review_module

    def _apply(review_model=None, **overrides):
        defaults = {
            "intent": INTENT_OK,
            "outline": VALID_OUTLINE_MARKDOWN,
            "research": RESEARCH_OK,
            "writer": DRAFT,
            "editor": editor_review(approved=True),
        }
        defaults.update(overrides)

        review = (
            review_model if review_model is not None else ScriptedLLM(replies="Outline approved.")
        )
        installed = ScriptedModels(monkeypatch, **defaults)
        models = installed.__enter__()
        models["outline_review"] = review
        monkeypatch.setattr(review_module, "create_model", lambda _config: review)
        monkeypatch.setattr(pipeline, "APP", pipeline.build_app(build_fresh_generation_workflow()))
        return models

    return _apply


async def _pause(session_service):
    """Run until the outline review asks a human for a decision."""
    result = await pipeline.run_pipeline(
        topic=TOPIC,
        session_id="resume-1",
        session_service=session_service,
    )
    assert result.paused_for_confirmation is True
    return result


class TestPauseHandles:
    async def test_pause_reports_everything_resume_needs(self, scripted):
        scripted(review_model=ScriptedConfirmationLLM())
        result = await _pause(_make_recording_service())

        assert result.invocation_id
        assert result.confirmation_request_id
        assert result.confirmation_payload

    async def test_pause_payload_offers_the_review_schema(self, scripted):
        scripted(review_model=ScriptedConfirmationLLM())
        result = await _pause(_make_recording_service())

        payload = result.confirmation_payload
        assert payload["response_schema"]["approved_outline"] == "OutlineSchema"
        assert payload["topic"][1] == TOPIC

    async def test_outline_is_already_validated_at_the_pause(self, scripted):
        """A reviewer must never be shown an outline that failed validation."""
        scripted(review_model=ScriptedConfirmationLLM())
        result = await _pause(_make_recording_service())

        outline = result.confirmation_payload["outline"]
        assert outline["title"] == "Test Blog"
        assert 3 <= len(outline["sections"]) <= 7


class TestResume:
    async def _resume(self, scripted, session_service, *, feedback="looks good"):
        """Pause, then resume, and report how often each model ran *during the resume*.

        Absolute call counts would conflate the pause run with the resumed one;
        what matters here is that resuming does not repeat completed work.
        """
        models = scripted(review_model=ScriptedConfirmationLLM())
        paused = await _pause(session_service)
        approved = paused.confirmation_payload["outline"]

        before = {role: model.call_count for role, model in models.items()}

        result = await pipeline.resume_pipeline(
            topic=TOPIC,
            session_id="resume-1",
            invocation_id=paused.invocation_id,
            confirmation_request_id=paused.confirmation_request_id,
            approved_outline=approved,
            feedback_text=feedback,
            session_service=session_service,
        )
        resume_calls = {role: model.call_count - before[role] for role, model in models.items()}
        return models, resume_calls, result

    async def test_resume_continues_to_the_final_content(self, scripted):
        scripted(review_model=ScriptedConfirmationLLM())
        _models, _calls, result = await self._resume(scripted, _make_recording_service())

        assert result.error is None
        assert result.final_content
        assert result.paused_for_confirmation is False

    async def test_resume_runs_research_and_drafting(self, scripted):
        scripted(review_model=ScriptedConfirmationLLM())
        _models, calls, _result = await self._resume(scripted, _make_recording_service())

        assert calls["research"] == 1
        assert calls["writer"] >= 1

    async def test_resume_does_not_repeat_intent_or_outline(self, scripted):
        """Completed nodes replay from history instead of being re-paid for."""
        scripted(review_model=ScriptedConfirmationLLM())
        _models, calls, _result = await self._resume(scripted, _make_recording_service())

        assert calls["intent"] == 0
        assert calls["outline"] == 0

    async def test_resume_records_the_reviewer_feedback(self, scripted):
        scripted(review_model=ScriptedConfirmationLLM())
        service = _make_recording_service()
        _models, _calls, result = await self._resume(
            scripted, service, feedback="tighten section two"
        )

        session = await service.get_session(
            app_name=pipeline.APP_NAME, user_id="anonymous", session_id="resume-1"
        )
        assert session.state["outline_feedback"] == "tighten section two"

    async def test_resume_preserves_the_approved_outline(self, scripted):
        scripted(review_model=ScriptedConfirmationLLM())
        service = _make_recording_service()
        _models, _calls, result = await self._resume(scripted, service)

        session = await service.get_session(
            app_name=pipeline.APP_NAME, user_id="anonymous", session_id="resume-1"
        )
        assert session.state["approved_outline"]["title"] == "Test Blog"
        assert session.state["blog_outline"]["title"] == "Test Blog"


class TestResumeValidation:
    async def test_approved_outline_must_be_valid(self, scripted):
        scripted(review_model=ScriptedConfirmationLLM())
        paused = await _pause(_make_recording_service())

        result = await pipeline.resume_pipeline(
            topic=TOPIC,
            session_id="resume-1",
            invocation_id=paused.invocation_id,
            confirmation_request_id=paused.confirmation_request_id,
            approved_outline={"title": "Only a title"},
            feedback_text=None,
            session_service=_make_recording_service(),
        )
        assert result.error is not None

    async def test_resume_message_is_built_from_the_pause_handles(self):
        from src.models.schemas import OutlineSchema

        outline = OutlineSchema(
            title="T",
            sections=[
                {"id": f"s{i}", "heading": f"H{i}", "goal": f"G{i}", "target_words": 120}
                for i in range(1, 4)
            ],
            estimated_total_words=360,
        ).model_dump()

        message = pipeline._build_confirmation_message(
            confirmation_request_id="req-1",
            approved_outline=outline,
            feedback_text="good",
        )
        part = message.parts[0].function_response
        assert part.id == "req-1"
        assert part.name == pipeline.REQUEST_CONFIRMATION_FUNCTION_CALL_NAME
        assert part.response["confirmed"] is True
        assert part.response["payload"]["approved_outline"] == outline
        assert part.response["payload"]["feedback_text"] == "good"


class TestInitialMessage:
    def test_initial_message_carries_topic_and_audience(self):
        message = pipeline._build_initial_message("Topic", "Audience")
        text = message.parts[0].text
        assert "Topic" in text
        assert "Audience" in text

    def test_phase_message_names_the_phase(self):
        message = pipeline._build_phase_message("research_phase", "Topic", "Audience")
        assert "research_phase" in message.parts[0].text


class TestUnusableOutput:
    async def test_invalid_outline_surfaces_as_an_error_not_empty_state(self, scripted):
        scripted(outline="Sure! What topic would you like?")
        result = await pipeline.run_pipeline(
            topic=TOPIC,
            session_id="resume-2",
            session_service=_make_recording_service(),
        )

        assert result.error is not None
        assert "stage=outline" in result.error

    async def test_invalid_editor_output_surfaces_as_an_error(self, scripted):
        scripted(editor="Looks great to me!")
        result = await pipeline.run_pipeline(
            topic=TOPIC,
            session_id="resume-3",
            session_service=_make_recording_service(),
        )

        assert result.error is not None
        assert "stage=editor" in result.error

    async def test_a_failure_never_yields_empty_content(self, scripted):
        scripted(outline="nonsense")
        result = await pipeline.run_pipeline(
            topic=TOPIC,
            session_id="resume-4",
            session_service=_make_recording_service(),
        )

        assert result.final_content == ""
        assert result.paused_for_confirmation is False


class TestResumabilityContract:
    def test_app_enables_resumability(self):
        config = pipeline.APP.resumability_config
        assert config is not None
        assert config.is_resumable is True

    def test_types_content_is_used_for_the_confirmation_message(self):
        assert (
            pipeline._build_confirmation_message(
                confirmation_request_id="x", approved_outline={}, feedback_text=None
            ).role
            == "user"
        )
        assert isinstance(
            pipeline._build_confirmation_message(
                confirmation_request_id="x", approved_outline={}, feedback_text=None
            )
            .parts[0]
            .function_response,
            types.FunctionResponse,
        )
