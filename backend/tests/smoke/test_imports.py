"""Smoke tests — verify the repo can be imported without ADK/GenAI installed.

These tests are the Phase 0 acceptance criteria. They must pass before any
schema or feature work begins.

Run with:
    pytest tests/smoke/ -v
"""
from __future__ import annotations

import importlib
import os

import pytest

# ---------------------------------------------------------------------------
# Smoke: config imports
# ---------------------------------------------------------------------------


def test_import_config_no_adk_error():
    """src.config must be importable without google-genai."""
    mod = importlib.import_module("src.config")
    assert mod is not None


def test_import_env_config():
    mod = importlib.import_module("src.config.env_config")
    assert hasattr(mod, "config")


def test_import_budget_config():
    mod = importlib.import_module("src.config.budget_config")
    assert hasattr(mod, "budget_settings")


def test_import_logging_config():
    mod = importlib.import_module("src.config.logging_config")
    assert hasattr(mod, "get_logger")


def test_agent_config_modelconfig_importable():
    """ModelConfig dataclasses must be importable without google-genai."""
    from src.config.agent_config import (
        CHATBOT_MODEL,
        EDITOR_MODEL,
        INTENT_MODEL,
        ModelConfig,
        OUTLINE_MODEL,
        RESEARCH_MODEL,
        WRITER_MODEL,
    )
    assert INTENT_MODEL.name.startswith("gemini")
    assert isinstance(CHATBOT_MODEL, ModelConfig)


# ---------------------------------------------------------------------------
# Smoke: guards, core, monitoring imports
# ---------------------------------------------------------------------------


def test_import_guards():
    for sub in ("input_guard", "output_guard", "budget_guard", "rate_limit_guard", "validation_guard"):
        mod = importlib.import_module(f"src.guards.{sub}")
        assert mod is not None


def test_import_core():
    for sub in ("backpressure", "errors", "idempotency", "sanitization", "task_queue"):
        mod = importlib.import_module(f"src.core.{sub}")
        assert mod is not None


def test_import_monitoring():
    for sub in ("metrics", "cost_tracker", "circuit_breaker"):
        mod = importlib.import_module(f"src.monitoring.{sub}")
        assert mod is not None


# ---------------------------------------------------------------------------
# Smoke: API app construction
# ---------------------------------------------------------------------------


def test_import_api_main():
    """src.api.main must be importable — this is the critical smoke gate."""
    mod = importlib.import_module("src.api.main")
    assert hasattr(mod, "app"), "FastAPI app object not found in src.api.main"


def test_fastapi_app_is_constructible():
    from src.api.main import app
    from fastapi import FastAPI
    assert isinstance(app, FastAPI)


def test_health_route_exists():
    from src.api.main import app
    routes = [route.path for route in app.routes]  # type: ignore[union-attr]
    health_routes = [r for r in routes if "health" in r]
    assert health_routes, f"No health route found in {routes}"


def test_canonical_placeholder_routes_are_hidden_by_default():
    from src.api.main import app

    routes = [route.path for route in app.routes]  # type: ignore[union-attr]
    assert "/api/v1/blogs/generate" not in routes
    assert "/internal/ai/blogs" not in routes


# ---------------------------------------------------------------------------
# Smoke: worker module import
# ---------------------------------------------------------------------------


def test_import_worker_module():
    """Worker module must be importable without triggering LLM calls."""
    mod = importlib.import_module("src.workers.blog_worker")
    assert mod is not None


# ---------------------------------------------------------------------------
# Smoke: schema imports
# ---------------------------------------------------------------------------


def test_import_pydantic_schemas():
    from src.models.schemas import (
        EditorReviewSchema,
        FinalBlogSchema,
        IntentSchema,
        OutlineSchema,
        ResearchDataSchema,
    )
    # constructible with valid data
    intent = IntentSchema(status="CLEAR", message="Topic is clear and specific")
    assert intent.status == "CLEAR"
