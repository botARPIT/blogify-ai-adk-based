"""Session state schema.

The pipeline seeds session state and the executor writes it back to Postgres.
Both used to enumerate the keys independently, so a key could be added to one
side and forgotten on the other -- and the failure would be silent. These tests
make that drift loud.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from src.workflows.state_schema import (
    REFINEMENT_ITERATIONS_KEY,
    SESSION_STATE_KEYS,
    build_session_state,
    empty_session_state,
    missing_session_state_keys,
)


class TestSchemaShape:
    def test_schema_has_the_ten_session_keys(self):
        assert len(SESSION_STATE_KEYS) == 10
        assert len(set(SESSION_STATE_KEYS)) == 10

    def test_refinement_counter_is_not_a_session_key(self):
        """Per-invocation state; persisting it would mis-bound the next run."""
        assert REFINEMENT_ITERATIONS_KEY not in SESSION_STATE_KEYS

    def test_keys_are_sorted_by_pipeline_stage(self):
        """Order mirrors the flow so the tuple reads as the lifecycle."""
        assert SESSION_STATE_KEYS == (
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
        )


class TestEmptySessionState:
    def test_seeds_every_key(self):
        state = empty_session_state()
        assert set(state) == set(SESSION_STATE_KEYS)
        assert missing_session_state_keys(state) == set()

    def test_records_topic_and_audience(self):
        state = empty_session_state("Testing graphs", "engineers")
        assert state["topic"] == "Testing graphs"
        assert state["audience"] == "engineers"

    def test_stages_start_empty(self):
        state = empty_session_state()
        for key in (
            "intent_result",
            "blog_outline",
            "approved_outline",
            "outline_review_result",
            "research_data",
            "editor_review",
        ):
            assert state[key] == {}, key
        assert state["blog_draft"] == ""
        assert state["outline_feedback"] == ""

    def test_seeds_do_not_share_mutable_defaults(self):
        """Two sessions must not share one dict object."""
        first = empty_session_state()
        second = empty_session_state()
        first["blog_outline"]["mutated"] = True
        assert second["blog_outline"] == {}


class TestBuildSessionState:
    def test_includes_every_key(self):
        state = build_session_state(topic="t", audience="a")
        assert missing_session_state_keys(state) == set()

    def test_carries_the_values_it_is_given(self):
        state = build_session_state(
            topic="t",
            audience="a",
            intent_result={"status": "CLEAR"},
            blog_outline={"title": "T"},
            approved_outline={"title": "T"},
            outline_feedback="good",
            outline_review_result={"status": "approved"},
            research_data={"sources": []},
            blog_draft="draft",
            editor_review={"approved": True},
        )
        assert state["intent_result"]["status"] == "CLEAR"
        assert state["blog_outline"]["title"] == "T"
        assert state["outline_feedback"] == "good"
        assert state["blog_draft"] == "draft"
        assert state["editor_review"]["approved"] is True

    def test_absent_values_become_empty_not_none(self):
        state = build_session_state(topic="t", audience="a")
        assert state["blog_outline"] == {}
        assert state["blog_draft"] == ""
        assert state["outline_feedback"] == ""

    def test_rejects_a_key_outside_the_schema(self):
        """An unknown field is a TypeError, so it cannot be silently stored."""
        with pytest.raises(TypeError):
            build_session_state(topic="t", audience="a", rogue={"x": 1})  # type: ignore[call-arg]


class TestNoDriftBetweenLayers:
    """The regression this module exists to prevent."""

    @staticmethod
    def _dict_keys_in(path: str, function: str) -> set[str]:
        """Extract the literal string keys of the first dict a function returns."""
        source = pathlib.Path(path).read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == function:
                for inner in ast.walk(node):
                    if isinstance(inner, ast.Return) and isinstance(inner.value, ast.Dict):
                        return {
                            key.value for key in inner.value.keys if isinstance(key, ast.Constant)
                        }
        return set()

    def test_executor_snapshot_covers_the_schema(self):
        """The executor builds its snapshot through the schema, so it cannot drift."""
        executor_keys = self._dict_keys_in("src/workers/executor.py", "_build_state_snapshot")
        # No inline dict literal means it delegates to build_session_state.
        assert executor_keys == set(), (
            "_build_state_snapshot should build via build_session_state(), "
            f"not an inline dict; found {sorted(executor_keys)}"
        )

    def test_executor_snapshot_matches_the_schema_at_runtime(self):
        from src.workers.executor import PipelineExecutor

        executor = PipelineExecutor.__new__(PipelineExecutor)
        snapshot = executor._build_state_snapshot(
            job=_FakeJob(),
            result=_FakeResult(),
            feedback_text=None,
        )
        assert set(snapshot) == set(SESSION_STATE_KEYS)
        assert missing_session_state_keys(snapshot) == set()

    def test_pipeline_seed_matches_the_schema_at_runtime(self):
        from src.agents.pipeline import _initial_state

        assert set(_initial_state("t", "a")) == set(SESSION_STATE_KEYS)

    def test_seed_and_snapshot_agree_key_for_key(self):
        """Both sides derive from the same definition."""
        from src.agents.pipeline import _initial_state

        seed = _initial_state("t", "a")
        snapshot = build_session_state(topic="t", audience="a")
        assert set(seed) == set(snapshot)

    def test_pipeline_seed_delegates_to_the_schema(self):
        from src.agents.pipeline import _initial_state

        assert _initial_state("topic", "audience") == empty_session_state("topic", "audience")

    def test_a_key_added_to_one_side_only_would_be_caught(self):
        """Guards the test itself against going stale."""
        assert len(SESSION_STATE_KEYS) == len(set(SESSION_STATE_KEYS))
        assert "refinement_iterations" not in SESSION_STATE_KEYS


class _FakeJob:
    topic = "Testing graphs"
    audience = "engineers"
    approved_outline = None


class _FakeResult:
    intent_result = {"status": "CLEAR"}
    outline = {"title": "T"}
    research = {"sources": []}
    draft = "draft"
    editor_review = {"approved": True}
    confirmation_payload = None
    final_content = "draft"
