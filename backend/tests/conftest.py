"""pytest configuration and shared fixtures."""

import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ["ENVIRONMENT"] = "dev"
os.environ["GOOGLE_API_KEY"] = "test-api-key"
os.environ["TAVILY_API_KEY"] = "test-tavily-key"
os.environ["DATABASE_URL"] = "postgresql+asyncpg://test:test@localhost:5432/test"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"
os.environ["ENABLE_CANONICAL_ROUTES"] = "false"


@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def mock_db_session():
    """Mock async database session."""
    session = AsyncMock()
    session.execute = AsyncMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.add = MagicMock()
    session.close = AsyncMock()
    return session


@pytest.fixture
def mock_redis():
    """Mock Redis client."""
    redis = AsyncMock()
    redis.ping = AsyncMock(return_value=True)
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock(return_value=True)
    redis.lpush = AsyncMock(return_value=1)
    redis.rpop = AsyncMock(return_value=None)
    redis.zadd = AsyncMock(return_value=1)
    redis.zrem = AsyncMock(return_value=1)
    redis.zrangebyscore = AsyncMock(return_value=[])
    redis.evalsha = AsyncMock(return_value=None)
    redis.eval = AsyncMock(return_value=None)
    redis.script_load = AsyncMock(return_value="test_sha")
    redis.keys = AsyncMock(return_value=[])
    return redis


@pytest.fixture
def mock_session_factory(mock_db_session):
    """Mock AsyncSessionFactory."""
    factory = AsyncMock()
    factory.__aenter__ = AsyncMock(return_value=mock_db_session)
    factory.__aexit__ = AsyncMock(return_value=None)
    return factory


@pytest.fixture
def test_client():
    """Create test client."""
    with patch("src.core.database.AsyncSessionFactory"):
        with patch("src.core.redis_pool.get_redis_client", new_callable=AsyncMock):
            from src.api.main import app
            return TestClient(app)


@pytest.fixture
def mock_blog_session():
    """Mock BlogSession object."""
    session = MagicMock()
    session.id = 1
    session.user_id = 1
    session.topic = "Test Topic"
    session.audience = "test audience"
    session.tone = "professional"
    session.status = "QUEUED"
    session.current_stage = None
    session.adk_session_id = "test-adk-session"
    session.budget_reserved_tokens = 50000
    session.budget_reserved_usd = 1.0
    session.budget_spent_tokens = 0
    session.budget_spent_usd = 0
    session.reap_count = 0
    session.idempotency_key = None
    session.created_at = None
    session.updated_at = None
    session.completed_at = None
    session.failed_at = None
    session.failure_reason = None
    return session


@pytest.fixture
def mock_agent_run():
    """Mock AgentRun object."""
    run = MagicMock()
    run.id = 1
    run.blog_session_id = 1
    run.stage_name = "intent"
    run.agent_name = "intent"
    run.model_name = "gemini-2.0-flash"
    run.status = "COMPLETED"
    run.prompt_tokens = 100
    run.completion_tokens = 50
    run.total_tokens = 150
    run.cost_usd = 0.000003
    run.latency_ms = 1000
    run.output_snapshot = {"stage": "intent", "costs": {}}
    run.error_message = None
    run.started_at = None
    run.completed_at = None
    return run


@pytest.fixture
def mock_research_source():
    """Mock ResearchSource object."""
    source = MagicMock()
    source.id = 1
    source.blog_session_id = 1
    source.user_id = 1
    source.title = "Test Source"
    source.url = "https://example.com"
    source.content = "Test content"
    source.score = 0.9
    source.topic = "test"
    source.collected_at = None
    return source


@pytest.fixture
def valid_blog_request():
    """Valid blog generation request."""
    return {
        "topic": "The Future of Artificial Intelligence in Healthcare",
        "audience": "healthcare professionals",
        "tone": "professional"
    }


@pytest.fixture
def invalid_blog_request():
    """Invalid blog request (topic too short)."""
    return {
        "topic": "AI",
        "audience": "developers",
        "tone": "professional"
    }