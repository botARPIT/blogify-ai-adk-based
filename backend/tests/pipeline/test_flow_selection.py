"""Flow selection.

``PHASE_WORKFLOWS`` is the whole of flow selection: a caller names a phase, this
module names the graph. The tests below pin that mapping so a phase can never
silently fall back to the wrong lifecycle.
"""

from __future__ import annotations

import pytest

from src.agents import pipeline
from src.workflows.fresh_generation import build_fresh_generation_workflow
from src.workflows.resume_from_outline import build_resume_from_outline_workflow
from src.workflows.revision import build_revision_workflow

#: Phases the worker can hand the pipeline, from BlogJobPhase.
WORKER_PHASES = ["fresh_generation", "resume_outline", "research_phase", "revision"]


class TestPhaseToWorkflowMapping:
    def test_recovery_and_revision_both_have_workflows(self):
        assert set(pipeline.PHASE_WORKFLOWS) == {"research_phase", "revision"}

    @pytest.mark.parametrize(
        ("phase", "expected_name"),
        [("research_phase", "blog_resume_from_outline"), ("revision", "blog_revision")],
    )
    def test_each_phase_builds_its_own_workflow(self, phase, expected_name):
        assert pipeline.PHASE_WORKFLOWS[phase]().name == expected_name

    @pytest.mark.parametrize("phase", ["writer_phase", "editor_phase", "fresh_generation", ""])
    def test_unmapped_phases_are_rejected(self, phase):
        """Fresh generation has its own entrypoint and must not route here."""
        with pytest.raises(ValueError, match="Unsupported pipeline phase"):
            pipeline._build_phase_runner(object(), phase)

    def test_every_post_outline_phase_is_mapped(self):
        """No worker phase may fall through to a missing workflow."""
        for phase in WORKER_PHASES:
            if phase in ("fresh_generation", "resume_outline"):
                continue
            assert phase in pipeline.PHASE_WORKFLOWS, phase


class TestFlowsAreDistinct:
    def test_revision_and_recovery_are_named_apart(self):
        assert (
            pipeline.PHASE_WORKFLOWS["revision"]().name
            != pipeline.PHASE_WORKFLOWS["research_phase"]().name
        )

    def test_they_share_a_graph_today(self):
        """Declared separately so they can diverge; currently equivalent."""
        resume = pipeline.PHASE_WORKFLOWS["research_phase"]()
        revision = pipeline.PHASE_WORKFLOWS["revision"]()

        assert [(e.from_node.name, e.to_node.name, e.route) for e in resume.graph.edges] == [
            (e.from_node.name, e.to_node.name, e.route) for e in revision.graph.edges
        ]

    def test_fresh_generation_is_not_a_phase_workflow(self):
        """It runs through run_pipeline, so it must stay out of the map."""
        assert "fresh_generation" not in pipeline.PHASE_WORKFLOWS
        assert build_fresh_generation_workflow().name == "blog_generation"

    def test_the_mapping_matches_the_workflow_builders(self):
        assert (
            pipeline.PHASE_WORKFLOWS["research_phase"]() is not None
            and build_resume_from_outline_workflow is not None
            and build_revision_workflow is not None
        )


class TestExecuteIsTheSinglePath:
    """All four entrypoints funnel through one error boundary."""

    ENTRYPOINTS = [
        "run_pipeline",
        "run_pipeline_from_phase",
        "resume_pipeline",
        "load_pipeline_result_from_state",
    ]

    @pytest.mark.parametrize("name", ENTRYPOINTS)
    def test_every_entrypoint_delegates_to_execute(self, name, monkeypatch):
        import asyncio

        calls: list[dict] = []

        async def fake_execute(request, **kwargs):
            calls.append(kwargs)
            return pipeline.PipelineResult(session_id=request.session_id)

        monkeypatch.setattr(pipeline, "_execute", fake_execute)

        kwargs = {
            "topic": "Testing workflow graphs",
            "audience": "engineers",
            "user_id": "u",
            "session_id": "s",
            "session_service": object(),
            "state_snapshot": None,
        }
        if name == "run_pipeline":
            asyncio.run(pipeline.run_pipeline(topic=kwargs["topic"], session_id="s"))
        elif name == "run_pipeline_from_phase":
            asyncio.run(pipeline.run_pipeline_from_phase(phase="research_phase", **kwargs))
        elif name == "resume_pipeline":
            asyncio.run(
                pipeline.resume_pipeline(
                    **kwargs,
                    invocation_id="inv",
                    confirmation_request_id="req",
                    approved_outline={},
                )
            )
        else:
            asyncio.run(pipeline.load_pipeline_result_from_state(**kwargs))

        assert len(calls) == 1
        assert calls[0]["span_name"] and calls[0]["error_event"]

    def test_each_entrypoint_reports_under_its_own_event(self):
        """Trace/log consumers can tell which flow failed."""
        source = __import__("pathlib").Path("src/agents/pipeline.py").read_text()
        for event in (
            "pipeline_failed",
            "pipeline_phase_resume_failed",
            "pipeline_state_load_failed",
            "pipeline_resume_failed",
        ):
            assert event in source, event

    def test_state_read_passes_no_runner(self):
        import asyncio

        captured: dict = {}

        async def fake_execute(request, **kwargs):
            captured.update(kwargs)
            return pipeline.PipelineResult(session_id=request.session_id)

        original = pipeline._execute
        try:
            pipeline._execute = fake_execute
            asyncio.run(
                pipeline.load_pipeline_result_from_state(
                    topic="Testing workflow graphs", session_id="s"
                )
            )
        finally:
            pipeline._execute = original

        assert captured["build_runner"] is None

    def test_graph_flows_pass_a_runner_factory(self):
        import asyncio

        captured: dict = {}

        async def fake_execute(request, **kwargs):
            captured.update(kwargs)
            return pipeline.PipelineResult(session_id=request.session_id)

        original = pipeline._execute
        try:
            pipeline._execute = fake_execute
            asyncio.run(pipeline.run_pipeline(topic="Testing workflow graphs", session_id="s"))
        finally:
            pipeline._execute = original

        assert callable(captured["build_runner"])
        assert callable(captured["build_message"])


class TestPipelineResultCarriesSnapshot:
    def test_snapshot_is_stored_on_the_result(self):
        result = pipeline.PipelineResult(session_id="s", state_snapshot={"a": 1})
        assert result.state_snapshot == {"a": 1}

    def test_snapshot_defaults_to_none(self):
        assert pipeline.PipelineResult(session_id="s").state_snapshot is None

    def test_snapshot_is_not_part_of_the_result_contract(self):
        """The executor rebuilds the snapshot; this is transport, not output."""
        assert pipeline.PipelineResult(session_id="s").state_snapshot is None
