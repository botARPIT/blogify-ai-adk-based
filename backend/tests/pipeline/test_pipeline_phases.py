"""Phase-based resume used by worker recovery and revisions.

Covers ``run_pipeline_from_phase``: the post-outline graph, its routing, and the
refusal to run an unknown phase.
"""

from __future__ import annotations

import pytest

import src.agents.pipeline as pipeline
from src.workflows.common import MAX_REFINEMENT_ITERATIONS
from tests.fakes.scripted_llm import (
    DRAFT,
    RESEARCH_OK,
    ScriptedModels,
    editor_review,
)
from tests.pipeline.test_pipeline_pause import _make_recording_service

TOPIC = "Testing workflow graphs"


@pytest.fixture
def scripted(monkeypatch):
    def _apply(**overrides):
        defaults = {
            "research": RESEARCH_OK,
            "writer": DRAFT,
            "editor": editor_review(approved=True),
        }
        defaults.update(overrides)
        installed = ScriptedModels(monkeypatch, **defaults)
        models = installed.__enter__()
        return models

    return _apply


class TestResearchPhase:
    async def test_runs_research_then_drafting(self, scripted):
        models = scripted()
        result = await pipeline.run_pipeline_from_phase(
            phase="research_phase",
            topic=TOPIC,
            session_id="phase-1",
            session_service=_make_recording_service(),
        )

        assert result.error is None
        assert models["research"].call_count == 1
        assert models["writer"].call_count == 1
        assert result.editor_review["approved"] is True

    async def test_does_not_repeat_intent_or_outline(self, scripted):
        """The outline was already approved; regenerating it would discard the
        reviewer's edits and re-ask a question they already answered."""
        models = scripted()
        await pipeline.run_pipeline_from_phase(
            phase="research_phase",
            topic=TOPIC,
            session_id="phase-2",
            session_service=_make_recording_service(),
        )

        assert "intent" not in models
        assert "outline" not in models

    async def test_seeds_state_from_a_snapshot(self, scripted):
        scripted()
        service = _make_recording_service()
        await pipeline.run_pipeline_from_phase(
            phase="research_phase",
            topic=TOPIC,
            session_id="phase-3",
            session_service=service,
            state_snapshot={"blog_outline": {"title": "Approved outline"}},
        )

        assert service.updated
        assert service.updated[0]["blog_outline"] == {"title": "Approved outline"}


class TestRevisionThroughPhases:
    async def test_rejection_then_approval_runs_the_writer_twice(self, scripted):
        models = scripted(
            editor=[
                editor_review(approved=False, feedback="Too thin"),
                editor_review(approved=True),
            ]
        )
        result = await pipeline.run_pipeline_from_phase(
            phase="research_phase",
            topic=TOPIC,
            session_id="phase-4",
            session_service=_make_recording_service(),
        )

        assert models["writer"].call_count == 2
        assert result.editor_review["approved"] is True

    async def test_never_approving_still_terminates(self, scripted):
        models = scripted(editor=editor_review(approved=False, feedback="No"))
        result = await pipeline.run_pipeline_from_phase(
            phase="research_phase",
            topic=TOPIC,
            session_id="phase-5",
            session_service=_make_recording_service(),
        )

        assert result.error is None
        assert models["writer"].call_count == MAX_REFINEMENT_ITERATIONS

    async def test_revision_overwrites_the_previous_draft(self, scripted):
        """The carried-forward draft is an input; the new run replaces it."""
        scripted()
        service = _make_recording_service()
        result = await pipeline.run_pipeline_from_phase(
            phase="research_phase",
            topic=TOPIC,
            session_id="phase-6",
            session_service=service,
            state_snapshot={"blog_draft": "previous version"},
        )

        # The snapshot was applied before the graph ran.
        assert service.updated[0]["blog_draft"] == "previous version"
        # And the phase run produced a fresh draft from it.
        assert result.draft == DRAFT

    async def test_revision_applies_the_approved_outline_snapshot(self, scripted):
        """The new version is written against the outline the user approved."""
        scripted()
        service = _make_recording_service()
        await pipeline.run_pipeline_from_phase(
            phase="research_phase",
            topic=TOPIC,
            session_id="phase-7",
            session_service=service,
            state_snapshot={"blog_outline": {"title": "Approved outline"}},
        )

        session = await service.get_session(
            app_name=pipeline.APP_NAME, user_id="anonymous", session_id="phase-7"
        )
        assert session.state["blog_outline"]["title"] == "Approved outline"


class TestUnknownPhase:
    @pytest.mark.parametrize("phase", ["writer_phase", "editor_phase", "nonsense", ""])
    def test_is_rejected(self, phase):
        with pytest.raises(ValueError, match="Unsupported pipeline phase"):
            pipeline._build_phase_runner(object(), phase)

    def test_every_post_outline_phase_has_a_workflow(self):
        """Recovery and revision are both real phases with a real graph."""
        assert set(pipeline.PHASE_WORKFLOWS) == {"research_phase", "revision"}

    def test_revision_phase_builds_the_revision_workflow(self):
        workflow = pipeline.PHASE_WORKFLOWS["revision"]()
        assert workflow.name == "blog_revision"

    def test_research_phase_builds_the_recovery_workflow(self):
        workflow = pipeline.PHASE_WORKFLOWS["research_phase"]()
        assert workflow.name == "blog_resume_from_outline"


class TestPhaseWorkflowSelection:
    def test_each_phase_has_its_own_workflow_name(self):
        workflow = pipeline.PHASE_WORKFLOWS["research_phase"]()
        assert workflow.name == "blog_resume_from_outline"

    def test_revision_workflow_is_distinct_but_equivalent(self):
        from src.workflows.resume_from_outline import build_resume_from_outline_workflow
        from src.workflows.revision import build_revision_workflow

        resume = build_resume_from_outline_workflow()
        revision = build_revision_workflow()

        assert resume.name != revision.name
        assert [(edge.from_node.name, edge.to_node.name) for edge in resume.graph.edges] == [
            (edge.from_node.name, edge.to_node.name) for edge in revision.graph.edges
        ]


class TestStateLoadOnly:
    async def test_load_from_state_runs_no_model(self, scripted):
        models = scripted()
        service = _make_recording_service()
        result = await pipeline.load_pipeline_result_from_state(
            topic=TOPIC,
            session_id="state-1",
            session_service=service,
            state_snapshot={
                "blog_outline": {"title": "Loaded"},
                "blog_draft": "loaded draft",
                "editor_review": {"approved": True, "final_blog": "final text"},
            },
        )

        assert result.error is None
        assert result.outline == {"title": "Loaded"}
        assert result.draft == "loaded draft"
        assert result.final_content == "final text"
        assert all(model.call_count == 0 for model in models.values())

    async def test_approved_editor_review_drives_final_content(self):
        service = _make_recording_service()
        result = await pipeline.load_pipeline_result_from_state(
            topic=TOPIC,
            session_id="state-2",
            session_service=service,
            state_snapshot={
                "blog_draft": "draft",
                "editor_review": {"approved": True, "final_blog": "polished"},
            },
        )

        assert result.final_content == "polished"

    async def test_unapproved_review_falls_back_to_the_draft(self):
        service = _make_recording_service()
        result = await pipeline.load_pipeline_result_from_state(
            topic=TOPIC,
            session_id="state-3",
            session_service=service,
            state_snapshot={
                "blog_draft": "draft",
                "editor_review": {"approved": False, "final_blog": ""},
            },
        )

        assert result.final_content == "draft"


class TestStateKeyStability:
    """Session keys the worker and the API already depend on."""

    @pytest.mark.parametrize(
        "key",
        [
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
        ],
    )
    def test_initial_state_keeps_the_key(self, key):
        assert key in pipeline._initial_state("topic", "audience")
