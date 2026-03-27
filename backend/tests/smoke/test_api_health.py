"""Smoke tests for root and health handlers."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_health_returns_healthy_payload():
    from src.api.routes.health import health_check

    response = await health_check()

    assert response["status"] == "healthy"
    assert response["service"] == "blogify-ai"


@pytest.mark.asyncio
async def test_root_returns_service_metadata():
    from src.api.main import root

    response = await root()

    assert response["status"] == "running"
    assert response["service"] == "Blogify AI API"
