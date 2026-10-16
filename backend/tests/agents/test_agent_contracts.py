"""Agent contract.

Agents are responsible for *what the model should do*: instruction, tools,
name, model selection, ADK configuration. They are not responsible for provider
routing, endpoint construction, parsing, normalization, or persistence.

These tests read the modules rather than the behaviour of a live provider, so
a violation shows up as a build-time contract failure instead of a confusing
runtime one.
"""

from __future__ import annotations

import ast
import importlib
import pathlib

import pytest

AGENT_MODULES = [
    "src.agents.intent_agent",
    "src.agents.outline_agent",
    "src.agents.outline_review_agent",
    "src.agents.research_agent",
    "src.agents.writer_agent",
    "src.agents.editor_agent",
]

PROVIDER_SYMBOLS = {
    "Gemini",
    "LiteLlm",
    "litellm",
    "ChatOllama",
    "AsyncClient",
    "OpenAI",
}


def _source(module_name: str) -> str:
    path = pathlib.Path(module_name.replace(".", "/") + ".py")
    return path.read_text()


def _imported_names(module_name: str) -> set[str]:
    tree = ast.parse(_source(module_name))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
            names.update(alias.name for alias in node.names)
    return names


class TestAgentsConstruct:
    @pytest.mark.parametrize("module_name", AGENT_MODULES)
    def test_agent_factory_builds(self, module_name):
        module = importlib.import_module(module_name)
        factory = next(
            (
                name
                for name in dir(module)
                if name.startswith("create_") and name.endswith("_agent")
            ),
            None,
        )
        assert factory is not None, f"{module_name} exposes no agent factory"

        agent = getattr(module, factory)()
        assert agent.name
        assert agent.instruction
        assert agent.model is not None

    @pytest.mark.parametrize("module_name", AGENT_MODULES)
    def test_module_level_singleton_exists(self, module_name):
        """Scripts and existing callers import the singleton."""
        module = importlib.import_module(module_name)
        singletons = [
            name
            for name, value in vars(module).items()
            if not name.startswith("_") and hasattr(value, "name") and hasattr(value, "instruction")
        ]
        assert singletons, f"{module_name} exposes no agent singleton"


class TestNoProviderLeakage:
    @pytest.mark.parametrize("module_name", AGENT_MODULES)
    def test_no_provider_module_is_imported(self, module_name):
        imported = _imported_names(module_name)
        leaked = imported & PROVIDER_SYMBOLS
        assert not leaked, f"{module_name} imports provider symbols {leaked}"

    @pytest.mark.parametrize("module_name", AGENT_MODULES)
    def test_model_is_built_through_the_factory(self, module_name):
        imported = _imported_names(module_name)
        assert "create_model" in imported, f"{module_name} does not use create_model"

    @pytest.mark.parametrize("module_name", AGENT_MODULES)
    def test_no_direct_model_construction(self, module_name):
        tree = ast.parse(_source(module_name))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in PROVIDER_SYMBOLS, (
                    f"{module_name} constructs {node.func.id} directly"
                )

    @pytest.mark.parametrize("module_name", AGENT_MODULES)
    def test_agent_does_not_import_the_normalizer(self, module_name):
        """Normalization belongs to the workflow, not to the agent."""
        tree = ast.parse(_source(module_name))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert "normalizer" not in node.module


class TestOutputSchemaIsNotUsed:
    """Provider-dependent enforcement must not sit on the agent."""

    @pytest.mark.parametrize("module_name", AGENT_MODULES)
    def test_no_output_schema_is_declared(self, module_name):
        tree = ast.parse(_source(module_name))
        offenders = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and any(kw.arg == "output_schema" for kw in node.keywords)
        ]
        assert not offenders, f"{module_name} still passes output_schema to ADK"

    def test_schema_modules_are_no_longer_imported_by_agents(self):
        """Agents no longer need the pydantic schemas they used to enforce."""
        for module_name in (
            "src.agents.outline_agent",
            "src.agents.intent_agent",
            "src.agents.editor_agent",
        ):
            tree = ast.parse(_source(module_name))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    assert not node.module.endswith("schemas"), (
                        f"{module_name} imports application schemas directly"
                    )


class TestOutputKeys:
    def test_schema_dependent_agents_write_raw_keys(self):
        """Raw output first; a deterministic node produces the typed value."""
        for module_name, expected in [
            ("src.agents.intent_agent", "intent_raw"),
            ("src.agents.outline_agent", "outline_raw"),
            ("src.agents.editor_agent", "editor_review_raw"),
        ]:
            module = importlib.import_module(module_name)
            factory = next(
                name
                for name in dir(module)
                if name.startswith("create_") and name.endswith("_agent")
            )
            assert getattr(module, factory)().output_key == expected

    def test_writer_keeps_the_draft_key(self):
        from src.agents.writer_agent import WRITER_INSTRUCTION, create_writer_agent

        assert create_writer_agent().output_key == "blog_draft"
        for state_key in (
            "topic",
            "audience",
            "approved_outline",
            "blog_outline",
            "research_data",
            "outline_feedback",
        ):
            assert f"{{{state_key}}}" in WRITER_INSTRUCTION
        assert "do not ask the user to provide them again" in WRITER_INSTRUCTION
        assert "research_data.sources[0]" in WRITER_INSTRUCTION

    def test_editor_prompt_preserves_numbered_source_mapping(self):
        from src.agents.editor_agent import EDITOR_INSTRUCTION

        assert "[1] is sources[0]" in EDITOR_INSTRUCTION
        assert "never invent a source or URL" in EDITOR_INSTRUCTION

    def test_research_keeps_its_key(self):
        from src.agents.research_agent import create_research_agent

        assert create_research_agent().output_key == "research_data"


class TestModelSelectionIsConfiguration:
    @pytest.mark.parametrize(
        ("module_name", "config_name"),
        [
            ("src.agents.intent_agent", "INTENT_MODEL"),
            ("src.agents.outline_agent", "OUTLINE_MODEL"),
            ("src.agents.outline_review_agent", "OUTLINE_REVIEW_MODEL"),
            ("src.agents.research_agent", "RESEARCH_MODEL"),
            ("src.agents.writer_agent", "WRITER_MODEL"),
            ("src.agents.editor_agent", "EDITOR_MODEL"),
        ],
    )
    def test_agent_imports_its_stage_config(self, module_name, config_name):
        imported = _imported_names(module_name)
        assert config_name in imported

    def test_agents_do_not_contain_model_names(self):
        """A model name in an agent means model choice leaked into code."""
        for module_name in AGENT_MODULES:
            source = _source(module_name)
            for needle in ("gpt-oss", "gemma4", "gemini-2.5", "openai/"):
                assert needle not in source, f"{module_name} hardcodes {needle}"
