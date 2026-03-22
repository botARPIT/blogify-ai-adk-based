"""Smoke tests — verify API health endpoint returns 200."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def client():
    with (
        patch("src.models.repository.db_repository") as mock_repo,
        patch("src.core.task_queue.task_queue") as mock_queue,
    ):
        mock_repo.get_or_create_user = AsyncMock(return_value=MagicMock(id=1))
        mock_queue.get_queue_stats = AsyncMock(return_value={"pending": 0})
        from src.api.main import app
        yield TestClient(app, raise_server_exceptions=False)


def test_health_returns_200(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200


def test_root_returns_200(client):
    resp = client.get("/")
    assert resp.status_code == 200
