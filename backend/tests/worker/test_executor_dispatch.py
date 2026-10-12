"""Executor dispatch and persistence routing.

This is the seam between the worker and the pipeline, and it had no coverage at
all: every other ``test_worker_*.py`` is an empty stub. These tests pin two
things.

* Which flow a job phase reaches. Flow selection belongs to the pipeline; this
  module must pass the phase through rather than hardcoding one.
* Which lifecycle transition a result produces.

No database and no provider are involved: the repositories and the delay are
replaced with recorders.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.agents import pipeline
from src.models.orm_models import BlogJobPhase
from src.workers import executor as executor_module
from src.workers.executor import PipelineExecutor

# ---------------------------------------------------------------------------
# Doubles
# ---------------------------------------------------------------------------


class FakeJob:
    def __init__(self, phase: str, **overrides: Any) -> None:
        self.session_id = 7
        self.user_id = 42
        self.topic = "Testing workflow graphs"
        self.audience = "engineers"
        self.adk_session_id = "adk-session-1"
        self.phase = phase
        self.invocation_id = "inv-1"
        self.confirmation_request_id = "req-1"
        self.approved_outline = {"title": "T"}
        self.feedback_text = "good"
        self.__dict__.update(overrides)


class Recorder:
    """Stands in for a repository or service, recording every method call."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)

        async def _record(*args: Any, **kwargs: Any) -> Any:
            self.calls.append((name, kwargs))
            return None

        return _record

    def names(self) -> list[str]:
        return [name for name, _ in self.calls]

    def kwargs_for(self, name: str) -> dict:
        return [kwargs for called, kwargs in self.calls if called == name][0]


class FakeVersion:
    def __init__(self, version_id: int = 100) -> None:
        self.id = version_id
        self.state_snapshot = {"blog_outline": {"title": "T"}}
        self.outline_data = {"title": "T"}
        self.approved_outline = {"title": "T"}
        self.invocation_id = "inv-1"
        self.confirmation_request_id = "req-1"


def build_executor(monkeypatch, *, result=None, version=FakeVersion()) -> PipelineExecutor:
    """A PipelineExecutor whose collaborators record instead of persisting."""
    ex = PipelineExecutor.__new__(PipelineExecutor)

    recorded = Recorder()
    ex._version_repo = recorded
    ex._session_repo = recorded
    ex._run_repo = recorded
    ex._sources_repo = recorded
    ex._budget_service = recorded

    async def _get_active(_session_id: int):
        return version

    ex._get_active_version = _get_active  # type: ignore[assignment]

    ex.result = result
    ex.recorded = recorded  # type: ignore[attr-defined]
    return ex


def ok_result(**overrides: Any) -> pipeline.PipelineResult:
    base = dict(
        session_id="adk-session-1",
        outline={"title": "T"},
        draft="draft",
        final_content="final",
        editor_review={"approved": True},
        intent_result={"status": "CLEAR"},
        research={"sources": []},
        costs=[],
    )
    base.update(overrides)
    return pipeline.PipelineResult(**base)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def pipeline_calls(monkeypatch):
    """Capture which pipeline entrypoint the executor invokes, and with what."""
    calls: list[tuple[str, dict]] = []

    def _fake(name, result=None):
        async def _run(**kwargs):
            calls.append((name, kwargs))
            return result if result is not None else ok_result()

        return _run

    monkeypatch.setattr(executor_module, "run_pipeline", _fake("run_pipeline"))
    monkeypatch.setattr(executor_module, "resume_pipeline", _fake("resume_pipeline"))
    monkeypatch.setattr(
        executor_module,
        "run_pipeline_from_phase",
        _fake("run_pipeline_from_phase"),
    )

    async def _no_delay():
        return None

    monkeypatch.setattr(executor_module, "agent_delay", _no_delay)
    return calls


class TestPhaseReachesTheRightFlow:
    @pytest.mark.parametrize(
        ("phase", "expected"),
        [
            (BlogJobPhase.FRESH_GENERATION.value, "run_pipeline"),
            (BlogJobPhase.RESUME_OUTLINE.value, "resume_pipeline"),
            (BlogJobPhase.RESEARCH_PHASE.value, "run_pipeline_from_phase"),
            (BlogJobPhase.REVISION.value, "run_pipeline_from_phase"),
        ],
    )
    async def test_each_phase_dispatches_correctly(
        self, monkeypatch, pipeline_calls, phase, expected
    ):
        ex = build_executor(monkeypatch)
        await ex.execute(FakeJob(phase))

        assert pipeline_calls
        assert pipeline_calls[0][0] == expected

    async def test_unknown_phase_fails_the_job(self, monkeypatch, pipeline_calls):
        ex = build_executor(monkeypatch)
        job = FakeJob("not_a_phase")

        await ex.execute(job)

        assert pipeline_calls == [], "an unknown phase must not reach the pipeline"
        # _handle_failure ran: it marks the session failed.
        assert "mark_failed" in ex.recorded.names()

    async def test_revision_passes_its_own_phase_through(self, monkeypatch, pipeline_calls):
        """The hardcoded ``research_phase`` is what made revision.py dead code."""
        ex = build_executor(monkeypatch)
        await ex.execute(FakeJob(BlogJobPhase.REVISION.value))

        _name, kwargs = pipeline_calls[0]
        assert kwargs["phase"] == "revision"

    async def test_recovery_passes_its_own_phase_through(self, monkeypatch, pipeline_calls):
        ex = build_executor(monkeypatch)
        await ex.execute(FakeJob(BlogJobPhase.RESEARCH_PHASE.value))

        _name, kwargs = pipeline_calls[0]
        assert kwargs["phase"] == "research_phase"

    @pytest.mark.parametrize(
        "phase", [BlogJobPhase.RESEARCH_PHASE.value, BlogJobPhase.REVISION.value]
    )
    async def test_post_outline_phases_are_mapped_in_the_pipeline(
        self, monkeypatch, pipeline_calls, phase
    ):
        """Whatever this module sends must exist in the pipeline's phase map."""
        ex = build_executor(monkeypatch)
        await ex.execute(FakeJob(phase))

        _name, kwargs = pipeline_calls[0]
        assert kwargs["phase"] in pipeline.PHASE_WORKFLOWS


class TestJobDataIsForwarded:
    async def test_carries_the_active_version_snapshot(self, monkeypatch, pipeline_calls):
        ex = build_executor(monkeypatch)
        await ex.execute(FakeJob(BlogJobPhase.FRESH_GENERATION.value))

        _name, kwargs = pipeline_calls[0]
        assert kwargs["state_snapshot"] == {"blog_outline": {"title": "T"}}

    async def test_missing_version_yields_no_snapshot(self, monkeypatch, pipeline_calls):
        ex = build_executor(monkeypatch, version=None)
        await ex.execute(FakeJob(BlogJobPhase.FRESH_GENERATION.value))

        _name, kwargs = pipeline_calls[0]
        assert kwargs["state_snapshot"] is None

    async def test_resume_forwards_the_confirmation_handles(self, monkeypatch, pipeline_calls):
        ex = build_executor(monkeypatch)
        await ex.execute(FakeJob(BlogJobPhase.RESUME_OUTLINE.value))

        name, kwargs = pipeline_calls[0]
        assert name == "resume_pipeline"
        assert kwargs["invocation_id"] == "inv-1"
        assert kwargs["confirmation_request_id"] == "req-1"
        assert kwargs["approved_outline"] == {"title": "T"}

    async def test_forwards_the_adk_session_id_not_the_database_id(
        self, monkeypatch, pipeline_calls
    ):
        """The pipeline addresses ADK sessions; the job carries both ids."""
        ex = build_executor(monkeypatch)
        job = FakeJob(BlogJobPhase.FRESH_GENERATION.value)

        await ex.execute(job)

        _name, kwargs = pipeline_calls[0]
        assert kwargs["session_id"] == "adk-session-1"
        assert kwargs["user_id"] == "42"


class TestResultRoutesToALifecycleState:
    async def test_success_moves_to_final_review(self, monkeypatch, pipeline_calls):
        ex = build_executor(monkeypatch)
        await ex.execute(FakeJob(BlogJobPhase.FRESH_GENERATION.value))

        names = ex.recorded.names()
        assert "update_status" in names
        assert "mark_failed" not in names
        assert ex.recorded.kwargs_for("update_status")["current_stage"] == "final_review"

    async def test_error_fails_the_session(self, monkeypatch):
        monkeypatch.setattr(executor_module, "run_pipeline", _returning(ok_result(error="boom")))

        async def _no_delay():
            return None

        monkeypatch.setattr(executor_module, "agent_delay", _no_delay)

        ex = build_executor(monkeypatch)
        await ex.execute(FakeJob(BlogJobPhase.FRESH_GENERATION.value))

        assert "mark_failed" in ex.recorded.names()
        assert "update_status" not in ex.recorded.names()

    async def test_outline_pause_is_persisted_as_awaiting_review(self, monkeypatch, pipeline_calls):
        """A pause is an application state, not an error."""
        ex = build_executor(monkeypatch)
        job = FakeJob(BlogJobPhase.FRESH_GENERATION.value)

        async def _pause(**_kwargs):
            return ok_result(
                paused_for_confirmation=True,
                invocation_id="inv-9",
                confirmation_request_id="req-9",
            )

        monkeypatch.setattr(executor_module, "run_pipeline", _pause)
        await ex.execute(job)

        names = ex.recorded.names()
        assert "update_status" in names
        assert "mark_failed" not in names
        assert ex.recorded.kwargs_for("update_status")["current_stage"] == "outline_review"

    async def test_pause_persists_the_resume_handles(self, monkeypatch, pipeline_calls):
        """Without these the user could never answer the review."""
        ex = build_executor(monkeypatch)

        async def _pause(**_kwargs):
            return ok_result(
                paused_for_confirmation=True,
                invocation_id="inv-9",
                confirmation_request_id="req-9",
                confirmation_payload={"outline": {"title": "T"}},
            )

        monkeypatch.setattr(executor_module, "run_pipeline", _pause)
        await ex.execute(FakeJob(BlogJobPhase.FRESH_GENERATION.value))

        version_kwargs = ex.recorded.kwargs_for("update_version_state")
        assert version_kwargs["invocation_id"] == "inv-9"
        assert version_kwargs["confirmation_request_id"] == "req-9"
        assert version_kwargs["job_phase"] == BlogJobPhase.RESUME_OUTLINE.value

    @pytest.mark.parametrize(
        "phase",
        [BlogJobPhase.RESUME_OUTLINE.value, BlogJobPhase.RESEARCH_PHASE.value],
    )
    async def test_post_outline_phases_do_not_pause(self, monkeypatch, phase):
        """Those flows have no review node; long-standing behaviour preserved."""

        async def _pause(**_kwargs):
            return ok_result(paused_for_confirmation=True)

        async def _no_delay():
            return None

        for name in ("run_pipeline", "resume_pipeline", "run_pipeline_from_phase"):
            monkeypatch.setattr(executor_module, name, _pause)
        monkeypatch.setattr(executor_module, "agent_delay", _no_delay)

        ex = build_executor(monkeypatch)
        await ex.execute(FakeJob(phase))

        names = ex.recorded.names()
        assert "update_status" in names, "treated as success, as before"
        assert "mark_failed" not in names


class TestSeparationOfConcerns:
    def test_executor_does_not_choose_the_workflow(self):
        """Flow names live in the pipeline, not here."""
        import inspect

        source = inspect.getsource(executor_module)
        for forbidden in ("blog_generation", "blog_revision", "blog_resume_from_outline"):
            assert forbidden not in source, f"{forbidden} does not belong in the executor"

    def test_executor_does_not_import_workflow_builders(self):
        import inspect

        assert "build_revision_workflow" not in inspect.getsource(executor_module)
        assert "build_fresh_generation_workflow" not in inspect.getsource(executor_module)

    def test_phase_sets_are_declared_next_to_each_other(self):
        assert executor_module._POST_OUTLINE_PHASES == frozenset(
            {BlogJobPhase.REVISION.value, BlogJobPhase.RESEARCH_PHASE.value}
        )
        assert executor_module._REVIEW_PHASES == frozenset({BlogJobPhase.FRESH_GENERATION.value})

    def test_the_two_phase_sets_do_not_overlap(self):
        assert not (executor_module._POST_OUTLINE_PHASES & executor_module._REVIEW_PHASES)


def _returning(result):
    async def _run(**_kwargs):
        return result

    return _run
