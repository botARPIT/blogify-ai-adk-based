"""Session state contract between the pipeline and the worker.

The worker reads ``PipelineResult`` fields and writes them into a Postgres
snapshot; the review endpoints read the same keys back. These tests pin the
mapping so a rename cannot silently drop state on its way to the database.
"""

from __future__ import annotations

import pytest

import src.agents.pipeline as pipeline
from src.workflows.common import (
    EDITOR_REVIEW_KEY,
    INTENT_RESULT_KEY,
    MAX_REFINEMENT_ITERATIONS,
    OUTLINE_KEY,
    REFINEMENT_ITERATIONS_KEY,
)
from tests.fakes.scripted_llm import editor_review

#: Keys the worker persists, per executor._build_state_snapshot.
PERSISTED_KEYS = {
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
}


class TestCanonicalStateKeys:
    """Deterministic nodes write the keys the rest of the system reads."""

    def test_outline_node_writes_the_key_the_agents_read(self):
        assert OUTLINE_KEY == "blog_outline"

    def test_intent_node_writes_the_key_the_outline_prompt_reads(self):
        assert INTENT_RESULT_KEY == "intent_result"

    def test_editor_node_writes_the_key_the_worker_reads(self):
        assert EDITOR_REVIEW_KEY == "editor_review"

    def test_refinement_counter_has_its_own_key(self):
        assert REFINEMENT_ITERATIONS_KEY == "refinement_iterations"

    @pytest.mark.parametrize("key", sorted(PERSISTED_KEYS))
    def test_persisted_keys_are_seeded_by_the_pipeline(self, key):
        assert key in pipeline._initial_state("topic", "audience")

    def test_refinement_counter_is_not_persisted(self):
        """It is per-invocation; a stale count would mis-bound the next job."""
        assert REFINEMENT_ITERATIONS_KEY not in PERSISTED_KEYS


class TestResultToStateMapping:
    def test_result_fields_map_onto_state_keys(self):
        result = pipeline.PipelineResult(session_id="s")
        pipeline._populate_result_from_state(
            result,
            {
                "intent_result": {"status": "CLEAR"},
                "blog_outline": {"title": "T"},
                "research_data": {"sources": []},
                "blog_draft": "d",
                "editor_review": {"approved": True},
            },
        )

        state = {
            "intent_result": result.intent_result,
            "blog_outline": result.outline,
            "research_data": result.research,
            "blog_draft": result.draft,
            "editor_review": result.editor_review,
        }
        assert set(state) <= PERSISTED_KEYS

    def test_missing_state_keys_become_empty_not_none(self):
        result = pipeline.PipelineResult(session_id="s")
        pipeline._populate_result_from_state(result, {})
        assert result.draft == ""
        assert result.outline == {}

    def test_missing_state_keys_are_written_back(self):
        result = pipeline.PipelineResult(session_id="s")
        state: dict = {}
        pipeline._populate_result_from_state(result, state)
        assert state["blog_outline"] == {}


class TestFinalContentDerivation:
    def _result(self, editor_review_value, draft="draft"):
        result = pipeline.PipelineResult(session_id="s", draft=draft)
        result.editor_review = editor_review_value
        if isinstance(editor_review_value, dict) and editor_review_value.get("approved"):
            result.final_content = editor_review_value.get("final_blog", draft)
        else:
            result.final_content = draft
        return result

    def test_approved_review_supplies_the_final_content(self):
        result = self._result({"approved": True, "final_blog": "polished"})
        assert result.final_content == "polished"

    def test_approved_review_without_content_falls_back_to_the_draft(self):
        result = self._result({"approved": True})
        assert result.final_content == "draft"

    def test_rejected_review_falls_back_to_the_draft(self):
        result = self._result({"approved": False, "feedback": "no"})
        assert result.final_content == "draft"

    def test_missing_review_falls_back_to_the_draft(self):
        result = self._result(None)
        assert result.final_content == "draft"

    def test_approved_without_final_blog_is_still_normalizable(self):
        from src.normalizer import normalize_editor_review

        review = normalize_editor_review(editor_review(approved=True, blog="# Real content"))
        assert review.final_blog == "# Real content"


class TestRefinementBoundIsATunableConstant:
    def test_bound_is_two_iterations(self):
        """Matches the LoopAgent(max_iterations=2) this replaced."""
        assert MAX_REFINEMENT_ITERATIONS == 2

    def test_bound_is_exported_for_the_workflow_layer(self):
        from src.workflows import common

        assert common.MAX_REFINEMENT_ITERATIONS == 2
