"""Workflow graph behaviour.

These tests exercise the *graph*: which node follows which, what the
deterministic nodes write, and how the revision cycle is bounded. They use a
scripted in-memory model and an in-memory session service, so they need no
model provider, Redis, or Postgres.
"""

from __future__ import annotations

import uuid

import pytest
from google.adk.runners import Runner
from google.adk.sessions.in_memory_session_service import InMemorySessionService
from google.genai import types

from src.workflows.common import (
    APP_NAME,
    MAX_REFINEMENT_ITERATIONS,
    build_app,
    normalize_outline_node,
    route_after_editor,
)
from src.workflows.fresh_generation import build_fresh_generation_workflow
from src.workflows.resume_from_outline import build_resume_from_outline_workflow
from src.workflows.revision import build_revision_workflow
from tests.fakes.scripted_llm import (
    DRAFT,
    INTENT_OK,
    RESEARCH_OK,
    VALID_OUTLINE_MARKDOWN,
    ScriptedConfirmationLLM,
    ScriptedModels,
    editor_review,
)

# ---------------------------------------------------------------------------
# Graph shape
# ---------------------------------------------------------------------------


def _edges(workflow) -> list[tuple[str, str, object]]:
    return [(edge.from_node.name, edge.to_node.name, edge.route) for edge in workflow.graph.edges]


class TestGraphShape:
    def test_fresh_generation_expresses_intent_outline_normalize_review(self):
        edges = _edges(build_fresh_generation_workflow())
        pairs = [(frm, to) for frm, to, _ in edges]

        assert ("__START__", "intent_classifier") in pairs
        assert ("intent_classifier", "normalize_intent_node") in pairs
        assert ("normalize_intent_node", "outline_agent") in pairs
        assert ("outline_agent", "normalize_outline_node") in pairs
        assert ("normalize_outline_node", "outline_review_agent") in pairs
        assert ("outline_review_agent", "research_agent") in pairs

    def test_normalize_outline_is_a_distinct_graph_node(self):
        """Normalization is visible in the graph, not hidden in a callback."""
        workflow = build_fresh_generation_workflow()
        names = {node.name for node in workflow.graph.nodes}
        assert "normalize_outline_node" in names
        assert "outline_agent" in names
        assert "normalize_outline_node" != "outline_agent"

    def test_resume_workflow_starts_at_research(self):
        edges = _edges(build_resume_from_outline_workflow())
        assert edges[0] == ("__START__", "research_agent", None)
        assert not any(frm == "outline_agent" for frm, _, _ in edges)

    def test_revision_reuses_the_post_outline_graph(self):
        """Composition, not a second copy of the graph."""
        resume = _edges(build_resume_from_outline_workflow())
        revision = _edges(build_revision_workflow())
        assert [(f, t) for f, t, _ in resume] == [(f, t) for f, t, _ in revision]
        assert build_revision_workflow().name != build_resume_from_outline_workflow().name

    def test_refinement_cycle_is_conditional_not_unconditional(self):
        edges = _edges(build_fresh_generation_workflow())
        back_edge = [e for e in edges if e[0] == "route_after_editor"]
        assert {e[2] for e in back_edge} == {"revise", "approve"}

    def test_graph_has_exactly_one_terminal_node(self):
        workflow = build_fresh_generation_workflow()
        assert workflow.graph._terminal_node_names == {"workflow_end"}


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


async def _run(
    workflow, session_service=None, *, message: str = "go", state: dict | None = None
) -> tuple[list, object]:
    """Run a workflow to completion against an in-memory session.

    Sessions start from the same seed the pipeline uses in production, so the
    agents' context variables resolve exactly as they do for a real job.
    """
    from src.agents.pipeline import _initial_state

    service = session_service or InMemorySessionService()
    app = build_app(workflow)
    runner = Runner(app=app, app_name=APP_NAME, session_service=service)
    session_id = f"wf-{uuid.uuid4()}"
    await service.create_session(
        app_name=APP_NAME,
        user_id="u",
        session_id=session_id,
        state=_initial_state("Test Topic", "general readers") if state is None else state,
    )

    events = []
    async for event in runner.run_async(
        user_id="u",
        session_id=session_id,
        new_message=types.Content(role="user", parts=[types.Part(text=message)]),
    ):
        events.append(event)

    session = await service.get_session(app_name=APP_NAME, user_id="u", session_id=session_id)
    return events, session


def _authors(events) -> set[str]:
    return {event.author for event in events if event.author}


class TestFreshGenerationPath:
    async def test_intent_then_outline_then_normalize_then_review(self, monkeypatch):
        with ScriptedModels(
            monkeypatch,
            intent=INTENT_OK,
            outline=VALID_OUTLINE_MARKDOWN,
            outline_review="Outline approved.",
            research=RESEARCH_OK,
            writer=DRAFT,
            editor=editor_review(approved=True),
        ):
            events, session = await _run(build_fresh_generation_workflow())

        authors = _authors(events)
        for expected in (
            "intent_classifier",
            "outline_agent",
            "outline_review_agent",
            "research_agent",
            "writer_agent",
            "editor_agent",
        ):
            assert expected in authors, f"{expected} did not run"

    async def test_outline_node_writes_validated_state(self, monkeypatch):
        with ScriptedModels(
            monkeypatch,
            intent=INTENT_OK,
            outline=VALID_OUTLINE_MARKDOWN,
            outline_review="Outline approved.",
            research=RESEARCH_OK,
            writer=DRAFT,
            editor=editor_review(approved=True),
        ):
            _, session = await _run(build_fresh_generation_workflow())

        outline = session.state["blog_outline"]
        assert outline["title"] == "Test Blog"
        assert len(outline["sections"]) == 3
        assert all("goal" in s and "target_words" in s for s in outline["sections"])

    async def test_intent_node_writes_validated_state(self, monkeypatch):
        with ScriptedModels(
            monkeypatch,
            intent=INTENT_OK,
            outline=VALID_OUTLINE_MARKDOWN,
            outline_review="Outline approved.",
            research=RESEARCH_OK,
            writer=DRAFT,
            editor=editor_review(approved=True),
        ):
            _, session = await _run(build_fresh_generation_workflow())

        assert session.state["intent_result"]["status"] == "CLEAR"

    async def test_raw_output_is_retained_alongside_normalized(self, monkeypatch):
        with ScriptedModels(
            monkeypatch,
            intent=INTENT_OK,
            outline=VALID_OUTLINE_MARKDOWN,
            outline_review="Outline approved.",
            research=RESEARCH_OK,
            writer=DRAFT,
            editor=editor_review(approved=True),
        ):
            _, session = await _run(build_fresh_generation_workflow())

        assert session.state["outline_raw"].startswith("**Title:** Test Blog")
        assert isinstance(session.state["blog_outline"], dict)


class TestEditorApprovalAndRevision:
    async def test_approved_editor_runs_the_writer_once(self, monkeypatch):
        with ScriptedModels(
            monkeypatch,
            intent=INTENT_OK,
            outline=VALID_OUTLINE_MARKDOWN,
            outline_review="Outline approved.",
            research=RESEARCH_OK,
            writer=DRAFT,
            editor=editor_review(approved=True),
        ) as models:
            _, session = await _run(build_fresh_generation_workflow())

        assert models["writer"].call_count == 1
        assert session.state["editor_review"]["approved"] is True

    async def test_revision_request_routes_back_to_the_writer(self, monkeypatch):
        """Editor asks for a revision -> writer runs again -> then approved."""
        with ScriptedModels(
            monkeypatch,
            intent=INTENT_OK,
            outline=VALID_OUTLINE_MARKDOWN,
            outline_review="Outline approved.",
            research=RESEARCH_OK,
            writer=DRAFT,
            editor=[
                editor_review(approved=False, feedback="Too thin"),
                editor_review(approved=True),
            ],
        ) as models:
            _, session = await _run(build_fresh_generation_workflow())

        assert models["writer"].call_count == 2
        assert models["editor"].call_count == 2
        assert session.state["editor_review"]["approved"] is True

    async def test_revision_cycles_are_bounded(self, monkeypatch):
        """A model that never approves must not spin forever."""
        with ScriptedModels(
            monkeypatch,
            intent=INTENT_OK,
            outline=VALID_OUTLINE_MARKDOWN,
            outline_review="Outline approved.",
            research=RESEARCH_OK,
            writer=DRAFT,
            editor=editor_review(approved=False, feedback="Still not good enough"),
        ) as models:
            _, session = await _run(build_fresh_generation_workflow())

        assert models["writer"].call_count == MAX_REFINEMENT_ITERATIONS
        assert models["editor"].call_count == MAX_REFINEMENT_ITERATIONS
        assert session.state["refinement_iterations"] == MAX_REFINEMENT_ITERATIONS

    async def test_rejection_at_the_bound_accepts_the_draft(self, monkeypatch):
        """Matches the old LoopAgent: out of iterations means stop, not fail."""
        with ScriptedModels(
            monkeypatch,
            intent=INTENT_OK,
            outline=VALID_OUTLINE_MARKDOWN,
            outline_review="Outline approved.",
            research=RESEARCH_OK,
            writer=DRAFT,
            editor=editor_review(approved=False, feedback="Nope"),
        ):
            _, session = await _run(build_fresh_generation_workflow())

        assert session.state["editor_review"]["approved"] is False


class TestInvalidModelOutput:
    async def test_unusable_outline_stops_the_graph(self, monkeypatch):
        """Bad output fails loudly rather than becoming empty state."""
        with ScriptedModels(
            monkeypatch,
            intent=INTENT_OK,
            outline="Sure! I'd be happy to help with that.",
            outline_review="Outline approved.",
            research=RESEARCH_OK,
            writer=DRAFT,
            editor=editor_review(approved=True),
        ):
            with pytest.raises(Exception) as exc:
                await _run(build_fresh_generation_workflow())

        assert "normalization failed" in str(exc.value).lower()

    async def test_failure_names_the_stage_and_agent(self, monkeypatch):
        with ScriptedModels(
            monkeypatch,
            intent=INTENT_OK,
            outline="",
            outline_review="Outline approved.",
            research=RESEARCH_OK,
            writer=DRAFT,
            editor=editor_review(approved=True),
        ):
            with pytest.raises(Exception) as exc:
                await _run(build_fresh_generation_workflow())

        message = str(exc.value)
        assert "stage=outline" in message
        assert "agent=outline_agent" in message

    async def test_unusable_editor_output_stops_the_graph(self, monkeypatch):
        with ScriptedModels(
            monkeypatch,
            intent=INTENT_OK,
            outline=VALID_OUTLINE_MARKDOWN,
            outline_review="Outline approved.",
            research=RESEARCH_OK,
            writer=DRAFT,
            editor="The draft reads well to me!",
        ):
            with pytest.raises(Exception) as exc:
                await _run(build_fresh_generation_workflow())

        assert "stage=editor" in str(exc.value)

    async def test_outline_review_never_runs_after_a_normalization_failure(self, monkeypatch):
        with ScriptedModels(
            monkeypatch,
            intent=INTENT_OK,
            outline="not an outline",
            outline_review="Outline approved.",
            research=RESEARCH_OK,
            writer=DRAFT,
            editor=editor_review(approved=True),
        ) as models:
            with pytest.raises(Exception):
                await _run(build_fresh_generation_workflow())

        assert models["outline_review"].call_count == 0


class TestOutlineReviewPause:
    """The human review boundary must keep pausing the same way it did."""

    async def _run_to_pause(self, monkeypatch):
        import src.agents.outline_review_agent as review_module
        from src.agents.pipeline import _initial_state

        review_model = ScriptedConfirmationLLM()
        with ScriptedModels(
            monkeypatch,
            intent=INTENT_OK,
            outline=VALID_OUTLINE_MARKDOWN,
            research=RESEARCH_OK,
            writer=DRAFT,
            editor=editor_review(approved=True),
        ):
            monkeypatch.setattr(review_module, "create_model", lambda _c: review_model)
            service = InMemorySessionService()
            app = build_app(build_fresh_generation_workflow())
            runner = Runner(app=app, app_name=APP_NAME, session_service=service)
            session_id = f"pause-{uuid.uuid4()}"
            await service.create_session(
                app_name=APP_NAME,
                user_id="u",
                session_id=session_id,
                state=_initial_state("Test Topic", "general readers"),
            )

            events = []
            async for event in runner.run_async(
                user_id="u",
                session_id=session_id,
                new_message=types.Content(role="user", parts=[types.Part(text="go")]),
            ):
                events.append(event)
        return events, service, session_id, runner, review_model

    @staticmethod
    def _confirmation(events):
        for event in events:
            for call in event.get_function_calls():
                if call.name == "adk_request_confirmation":
                    return event, call
        return None, None

    async def test_review_pauses_before_research(self, monkeypatch):
        events, *_ = await self._run_to_pause(monkeypatch)
        _, confirmation = self._confirmation(events)
        assert confirmation is not None

        authors = _authors(events)
        assert "outline_review_agent" in authors
        assert "research_agent" not in authors
        assert "writer_agent" not in authors

    async def test_pause_carries_the_validated_outline(self, monkeypatch):
        events, *_ = await self._run_to_pause(monkeypatch)
        _, confirmation = self._confirmation(events)
        payload = confirmation.args["toolConfirmation"]["payload"]
        assert payload["outline"]["title"] == "Test Blog"
        assert len(payload["outline"]["sections"]) == 3

    async def test_resume_continues_past_review_into_research(self, monkeypatch):
        events, service, session_id, runner, review_model = await self._run_to_pause(monkeypatch)
        event, confirmation = self._confirmation(events)

        resume_message = types.Content(
            role="user",
            parts=[
                types.Part(
                    function_response=types.FunctionResponse(
                        id=confirmation.id,
                        name="adk_request_confirmation",
                        response={
                            "confirmed": True,
                            "payload": {
                                "approved_outline": event
                                and confirmation.args["toolConfirmation"]["payload"]["outline"],
                                "feedback_text": "looks good",
                            },
                        },
                    )
                )
            ],
        )

        resume_events = []
        async for resumed in runner.run_async(
            user_id="u",
            session_id=session_id,
            invocation_id=event.invocation_id,
            new_message=resume_message,
        ):
            resume_events.append(resumed)

        session = await service.get_session(app_name=APP_NAME, user_id="u", session_id=session_id)
        authors = _authors(resume_events)
        assert "research_agent" in authors
        assert "writer_agent" in authors
        assert session.state["outline_feedback"] == "looks good"

    async def test_resume_does_not_rerun_completed_agents(self, monkeypatch):
        """Replay, not re-execution: intent and outline are not paid for twice."""
        events, service, session_id, runner, _ = await self._run_to_pause(monkeypatch)
        event, confirmation = self._confirmation(events)

        outline_payload = confirmation.args["toolConfirmation"]["payload"]["outline"]
        resume_message = types.Content(
            role="user",
            parts=[
                types.Part(
                    function_response=types.FunctionResponse(
                        id=confirmation.id,
                        name="adk_request_confirmation",
                        response={
                            "confirmed": True,
                            "payload": {
                                "approved_outline": outline_payload,
                                "feedback_text": "ok",
                            },
                        },
                    )
                )
            ],
        )

        resume_events = []
        async for resumed in runner.run_async(
            user_id="u",
            session_id=session_id,
            invocation_id=event.invocation_id,
            new_message=resume_message,
        ):
            resume_events.append(resumed)

        model_calls = [
            e
            for e in resume_events
            if e.author in ("intent_classifier", "outline_agent") and e.content
        ]
        assert model_calls == [], "replayed nodes re-queried the model"


class TestDeterministicNodes:
    async def test_normalize_outline_node_raises_on_unusable_input(self):
        from src.normalizer import NormalizationError

        class Ctx:
            state: dict = {}

        with pytest.raises(NormalizationError):
            normalize_outline_node(Ctx(), "just some prose")

    def test_route_after_editor_prefers_approval_within_bound(self):
        class Ctx:
            def __init__(self):
                self.state = {"editor_review": {"approved": True}}
                self.route = None

        ctx = Ctx()
        assert route_after_editor(ctx) == "approve"
        assert ctx.state["refinement_iterations"] == 1

    def test_route_after_editor_requests_revision_within_bound(self):
        class Ctx:
            def __init__(self):
                self.state = {"editor_review": {"approved": False}}
                self.route = None

        ctx = Ctx()
        assert route_after_editor(ctx) == "revise"

    def test_route_after_editor_accepts_at_the_bound(self):
        class Ctx:
            def __init__(self):
                self.state = {
                    "editor_review": {"approved": False},
                    "refinement_iterations": MAX_REFINEMENT_ITERATIONS - 1,
                }
                self.route = None

        ctx = Ctx()
        assert route_after_editor(ctx) == "approve"
        assert ctx.state["refinement_iterations"] == MAX_REFINEMENT_ITERATIONS


class TestPostOutlineWorkflows:
    async def test_resume_workflow_runs_research_through_editor(self, monkeypatch):
        with ScriptedModels(
            monkeypatch,
            research=RESEARCH_OK,
            writer=DRAFT,
            editor=editor_review(approved=True),
        ) as models:
            _, session = await _run(build_resume_from_outline_workflow())

        assert models["research"].call_count == 1
        assert models["writer"].call_count == 1
        assert session.state["editor_review"]["approved"] is True

    async def test_revision_workflow_supports_a_revision_cycle(self, monkeypatch):
        with ScriptedModels(
            monkeypatch,
            research=RESEARCH_OK,
            writer=DRAFT,
            editor=[
                editor_review(approved=False, feedback="Needs work"),
                editor_review(approved=True),
            ],
        ) as models:
            _, session = await _run(build_revision_workflow())

        assert models["writer"].call_count == 2
        assert session.state["editor_review"]["approved"] is True


class TestCostAttribution:
    async def test_agent_authors_are_preserved_for_cost_accounting(self, monkeypatch):
        """The worker bills per stage off ``event.author``."""
        with ScriptedModels(
            monkeypatch,
            intent=INTENT_OK,
            outline=VALID_OUTLINE_MARKDOWN,
            outline_review="Outline approved.",
            research=RESEARCH_OK,
            writer=DRAFT,
            editor=editor_review(approved=True),
        ):
            events, _ = await _run(build_fresh_generation_workflow())

        from src.agents.pipeline import STAGE_BY_AUTHOR

        billed = {
            STAGE_BY_AUTHOR[event.author]
            for event in events
            if event.author in STAGE_BY_AUTHOR and event.usage_metadata
        }
        assert {"intent", "outline", "writer", "editor"} <= billed
