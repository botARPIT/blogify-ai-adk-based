"""Stage fragments shared across flows.

The flows are declared explicitly; these fragments cover only the stages that
genuinely repeat. The tests below pin what each fragment contributes, and pin
that composing them produces exactly the documented graph -- so a flow file
stays readable as a statement of intent rather than a pile of edges.
"""

from __future__ import annotations

import pytest

from src.workflows.common import (
    build_agents,
    normalize_editor_review_node,
    normalize_intent_node,
    normalize_outline_node,
    post_outline_stages,
    pre_research_stages,
    route_after_editor,
    workflow_end,
)
from src.workflows.fresh_generation import build_fresh_generation_workflow
from src.workflows.resume_from_outline import build_resume_from_outline_workflow
from src.workflows.revision import build_revision_workflow


def _node_names(specs) -> list[tuple[str, str]]:
    """Normalise a fragment's plain edges into (from, to) name pairs.

    Conditional edges carry a dict as their destination and are inspected
    separately.
    """
    return [(str(spec[0]), str(spec[1])) for spec in specs if not isinstance(spec[1], dict)]


def _routed(specs) -> dict[str, dict]:
    """Map source node name -> {route: destination} for conditional edges.

    Several routed edges can leave the same node, so their destinations are
    merged rather than overwritten.
    """
    merged: dict[str, dict] = {}
    for spec in specs:
        if isinstance(spec[1], dict):
            merged.setdefault(str(spec[0]), {}).update(spec[1])
    return merged


def _graph_edges(workflow) -> list[tuple[str, str, object]]:
    return [(edge.from_node.name, edge.to_node.name, edge.route) for edge in workflow.graph.edges]


class TestPreResearchStages:
    def test_walks_start_intent_outline_review(self):
        agents = build_agents()

        assert _node_names(pre_research_stages(agents)) == [
            ("START", str(agents["intent"])),
            (str(agents["intent"]), str(normalize_intent_node)),
            (str(normalize_intent_node), str(agents["outline"])),
            (str(agents["outline"]), str(normalize_outline_node)),
            (str(normalize_outline_node), str(agents["outline_review"])),
        ]

    def test_a_normalizer_follows_each_expensive_agent(self):
        """Normalization is a visible node, not a hidden callback."""
        agents = build_agents()
        destinations = [to for _frm, to in _node_names(pre_research_stages(agents))]

        assert str(normalize_intent_node) in destinations
        assert str(normalize_outline_node) in destinations

    def test_starts_at_start_and_ends_at_the_review_agent(self):
        agents = build_agents()
        stages = _node_names(pre_research_stages(agents))

        assert stages[0][0] == "START"
        assert stages[-1][1] == str(agents["outline_review"])

    def test_does_not_reach_research(self):
        """What follows the review is the caller's decision, not the fragment's."""
        agents = build_agents()
        names = [
            name for spec in pre_research_stages(agents) for name in (str(spec[0]), str(spec[1]))
        ]
        assert str(agents["research"]) not in names


class TestPostOutlineStages:
    def test_walks_research_writer_editor(self):
        agents = build_agents()

        assert _node_names(post_outline_stages(agents))[:2] == [
            (str(agents["research"]), str(agents["writer"])),
            (str(agents["writer"]), str(agents["editor"])),
        ]

    def test_normalizes_the_editor_verdict(self):
        agents = build_agents()
        names = [name for _frm, name in _node_names(post_outline_stages(agents))]
        assert str(normalize_editor_review_node) in names

    def test_cycle_edges_are_routed_not_unconditional(self):
        """ADK rejects unconditional cycles; the revision bound depends on this."""
        routed = _routed(post_outline_stages(build_agents()))

        assert set(routed) == {str(route_after_editor)}
        assert set(routed[str(route_after_editor)]) == {"revise", "approve"}

    def test_revise_returns_to_the_writer_and_approve_ends(self):
        agents = build_agents()
        routes = _routed(post_outline_stages(agents))[str(route_after_editor)]

        assert routes["revise"] is agents["writer"]
        assert routes["approve"] is workflow_end

    def test_does_not_include_the_pre_research_stages(self):
        agents = build_agents()
        names = [
            name for spec in post_outline_stages(agents) for name in (str(spec[0]), str(spec[1]))
        ]
        assert str(agents["outline"]) not in names
        assert str(agents["intent"]) not in names


class TestFlowComposition:
    """Composing the fragments yields exactly the documented graph."""

    def test_fresh_generation_runs_both_halves(self):
        edges = _graph_edges(build_fresh_generation_workflow())
        names = {frm for frm, _to, _route in edges}

        assert "intent_classifier" in names
        assert "outline_agent" in names
        assert "outline_review_agent" in names
        assert "research_agent" in names

    def test_fresh_generation_leaves_review_for_research(self):
        """The one edge that only fresh generation owns stays explicit."""
        edges = _graph_edges(build_fresh_generation_workflow())
        assert ("outline_review_agent", "research_agent", None) in edges

    @pytest.mark.parametrize(
        "build",
        [build_resume_from_outline_workflow, build_revision_workflow],
        ids=["resume", "revision"],
    )
    def test_post_outline_flows_enter_at_research(self, build):
        assert _graph_edges(build())[0] == ("__START__", "research_agent", None)

    @pytest.mark.parametrize(
        "build",
        [build_resume_from_outline_workflow, build_revision_workflow],
        ids=["resume", "revision"],
    )
    def test_post_outline_flows_skip_the_pre_research_stages(self, build):
        edges = _graph_edges(build())
        names = {frm for frm, _to, _route in edges} | {to for _frm, to, _route in edges}
        assert "intent_classifier" not in names
        assert "outline_agent" not in names
        assert "outline_review_agent" not in names

    @pytest.mark.parametrize(
        "build",
        [
            build_fresh_generation_workflow,
            build_resume_from_outline_workflow,
            build_revision_workflow,
        ],
        ids=["fresh", "resume", "revision"],
    )
    def test_every_flow_ends_at_one_terminal_node(self, build):
        assert build().graph._terminal_node_names == {"workflow_end"}

    @pytest.mark.parametrize(
        "build",
        [
            build_fresh_generation_workflow,
            build_resume_from_outline_workflow,
            build_revision_workflow,
        ],
        ids=["fresh", "resume", "revision"],
    )
    def test_every_flow_compiles(self, build):
        """Graph validation runs at build time; a cycle error would raise here."""
        assert build() is not None

    def test_revision_and_resume_are_graphically_identical_today(self):
        """Declared separately so they may diverge; today they match."""
        assert _graph_edges(build_revision_workflow()) == _graph_edges(
            build_resume_from_outline_workflow()
        )

    def test_each_flow_has_its_own_name(self):
        names = {
            build_fresh_generation_workflow().name,
            build_resume_from_outline_workflow().name,
            build_revision_workflow().name,
        }
        assert len(names) == 3


class TestAgentSet:
    def test_constructs_every_agent_once(self):
        agents = build_agents()

        assert set(agents) == {
            "intent",
            "outline",
            "outline_review",
            "research",
            "writer",
            "editor",
        }

    def test_returns_distinct_instances(self):
        """Two calls must not hand back the same agent object."""
        first = build_agents()
        second = build_agents()

        assert first["writer"] is not second["writer"]
