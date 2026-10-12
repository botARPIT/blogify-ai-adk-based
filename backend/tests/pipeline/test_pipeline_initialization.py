"""Pipeline entrypoint contract.

The worker depends on these functions by name and keyword. This module pins the
public surface so an internal refactor cannot silently break the worker.
"""

from __future__ import annotations

import inspect

import pytest

from src.agents import pipeline


class TestPublicSurface:
    @pytest.mark.parametrize(
        "name",
        [
            "run_pipeline",
            "run_pipeline_from_phase",
            "resume_pipeline",
            "load_pipeline_result_from_state",
        ],
    )
    def test_entrypoint_is_exported(self, name):
        assert callable(getattr(pipeline, name))

    @pytest.mark.parametrize(
        "name", ["CostInfo", "PipelineResult", "APP", "APP_NAME", "STAGE_BY_AUTHOR"]
    )
    def test_shared_symbol_is_exported(self, name):
        assert hasattr(pipeline, name)

    def test_run_pipeline_signature_is_unchanged(self):
        signature = inspect.signature(pipeline.run_pipeline)
        assert list(signature.parameters) == [
            "topic",
            "session_id",
            "audience",
            "user_id",
            "session_service",
            "state_snapshot",
        ]

    def test_run_pipeline_from_phase_signature_is_unchanged(self):
        signature = inspect.signature(pipeline.run_pipeline_from_phase)
        for required in ("phase", "topic", "audience", "user_id", "session_id"):
            assert required in signature.parameters

    def test_resume_pipeline_accepts_the_confirmation_handles(self):
        """The pause/resume channel must not drift."""
        parameters = inspect.signature(pipeline.resume_pipeline).parameters
        for required in (
            "invocation_id",
            "confirmation_request_id",
            "approved_outline",
            "feedback_text",
        ):
            assert required in parameters

    def test_session_id_is_required(self):
        with pytest.raises(ValueError, match="session_id is required"):
            import asyncio

            asyncio.run(pipeline.run_pipeline(topic="t", session_id="  "))


class TestResultShape:
    def test_result_defaults(self):
        result = pipeline.PipelineResult(session_id="s")
        assert result.outline is None
        assert result.draft == ""
        assert result.costs == []
        assert result.error is None
        assert result.paused_for_confirmation is False

    def test_app_root_agent_is_a_workflow(self):
        from google.adk.workflow import Workflow

        assert isinstance(pipeline.APP.root_agent, Workflow)

    def test_stage_map_covers_every_ledgered_agent(self):
        assert set(pipeline.STAGE_BY_AUTHOR) == {
            "intent_classifier",
            "outline_agent",
            "research_agent",
            "writer_agent",
            "editor_agent",
        }


class TestPhaseRouting:
    def test_research_phase_maps_to_a_workflow_builder(self):
        assert "research_phase" in pipeline.PHASE_WORKFLOWS

    def test_unknown_phase_is_rejected(self):
        with pytest.raises(ValueError, match="Unsupported pipeline phase"):
            pipeline._build_phase_runner(object(), "writer_phase")


class TestInitialState:
    def test_state_seeds_every_key_the_prompts_read(self):
        state = pipeline._initial_state("topic", "audience")
        for key in (
            "topic",
            "audience",
            "intent_result",
            "blog_outline",
            "approved_outline",
            "outline_feedback",
            "outline_review_result",
            "research_data",
            "blog_draft",
            "editor_review",
        ):
            assert key in state

    def test_result_is_populated_from_state_keys(self):
        result = pipeline.PipelineResult(session_id="s")
        pipeline._populate_result_from_state(
            result,
            {
                "intent_result": {"status": "CLEAR"},
                "blog_outline": {"title": "T"},
                "research_data": {"sources": []},
                "blog_draft": "draft",
                "editor_review": {"approved": True},
            },
        )
        assert result.intent_result == {"status": "CLEAR"}
        assert result.outline == {"title": "T"}
        assert result.draft == "draft"
        assert result.editor_review == {"approved": True}


class TestPauseExtraction:
    class _Event:
        def __init__(self, calls, invocation_id="inv-1"):
            self._calls = calls
            self.invocation_id = invocation_id

        def get_function_calls(self):
            return self._calls

    class _Call:
        def __init__(self, name, call_id, args=None):
            self.name = name
            self.id = call_id
            self.args = args or {}

    def test_confirmation_is_detected(self):
        call = self._Call(
            pipeline.REQUEST_CONFIRMATION_FUNCTION_CALL_NAME,
            "req-1",
            {"toolConfirmation": {"payload": {"outline": {"title": "T"}}}},
        )
        paused, invocation_id, request_id, payload = pipeline._extract_pause_metadata(
            [self._Event([call])]
        )
        assert paused is True
        assert invocation_id == "inv-1"
        assert request_id == "req-1"
        assert payload == {"outline": {"title": "T"}}

    def test_no_confirmation_means_not_paused(self):
        event = self._Event([self._Call("some_tool", "x")])
        assert pipeline._extract_pause_metadata([event]) == (False, None, None, None)


class TestCostExtraction:
    class _Meta:
        def __init__(self, prompt, completion):
            self.prompt_token_count = prompt
            self.candidates_token_count = completion
            self.total_token_count = prompt + completion
            self.model_id = "m1"

    class _UsageEvent:
        def __init__(self, author, meta):
            self.author = author
            self.usage_metadata = meta
            self.content = None

    def test_costs_are_grouped_by_stage(self):
        events = [
            self._UsageEvent("intent_classifier", self._Meta(10, 5)),
            self._UsageEvent("outline_agent", self._Meta(20, 10)),
            self._UsageEvent("writer_agent", self._Meta(30, 15)),
        ]
        costs = {c.stage: c.total_tokens for c in pipeline._extract_costs_from_events(events)}
        assert costs == {"intent": 15, "outline": 30, "writer": 45}

    def test_unattributable_usage_falls_back_to_one_total(self):
        events = [self._UsageEvent("workflow_node", self._Meta(7, 3))]
        costs = pipeline._extract_costs_from_events(events)
        assert len(costs) == 1
        assert costs[0].stage == "full_pipeline"
        assert costs[0].total_tokens == 10

    def test_no_usage_yields_no_costs(self):
        assert pipeline._extract_costs_from_events([]) == []
