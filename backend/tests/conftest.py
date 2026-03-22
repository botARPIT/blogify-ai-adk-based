"""pytest configuration and shared fixtures."""

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# Set test environment - use 'dev' as it's a valid config value
os.environ["ENVIRONMENT"] = "dev"
os.environ["GOOGLE_API_KEY"] = "test-api-key"
os.environ["TAVILY_API_KEY"] = "test-tavily-key"
os.environ["DATABASE_URL"] = "postgresql+asyncpg://test:test@localhost:5432/test"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"



@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def mock_db_repository():
    """Mock database repository."""
    with patch("src.models.repository.db_repository") as mock:
        mock.get_or_create_user = AsyncMock(return_value=MagicMock(id=1, user_id="test_user"))
        mock.create_blog = AsyncMock(return_value=MagicMock(id=1, session_id="test-session"))
        mock.get_blog_by_session = AsyncMock(return_value=MagicMock(
            id=1,
            session_id="test-session",
            topic="Test Topic",
            audience="Test Audience",
            status="in_progress",
            current_stage="intent",
            stage_data={"status": "CLEAR"},
            word_count=0,
            sources_count=0,
            total_cost_usd=0.0,
            created_at=None,
            completed_at=None,
            title=None,
            content=None,
        ))
        mock.update_blog_stage = AsyncMock()
        mock.update_blog = AsyncMock()
        yield mock


@pytest.fixture
def mock_redis():
    """Mock Redis client."""
    with patch("src.guards.rate_limit_guard.redis_client") as mock:
        mock.get = AsyncMock(return_value=None)
        mock.set = AsyncMock(return_value=True)
        mock.incr = AsyncMock(return_value=1)
        mock.expire = AsyncMock(return_value=True)
        yield mock


@pytest.fixture
def mock_pipeline():
    """Mock blog generation pipeline."""
    with patch("src.agents.pipeline.blog_pipeline") as mock:
        mock.run_intent_stage = AsyncMock(return_value={
            "status": "CLEAR",
            "message": "Topic is clear",
            "topic": "Test Topic",
            "audience": "Test Audience"
        })
        mock.run_outline_stage = AsyncMock(return_value={
            "title": "Test Blog",
            "sections": [{"id": "intro", "heading": "Introduction"}],
            "estimated_total_words": 500
        })
        mock.run_research_stage = AsyncMock(return_value={
            "topic": "Test Topic",
            "summary": "Test summary",
            "sources": [{"title": "Source 1", "url": "https://example.com"}],
            "total_sources": 1
        })
        mock.run_writing_stage = AsyncMock(return_value={
            "title": "Test Blog",
            "content": "# Test Blog\n\nContent here...",
            "word_count": 500,
            "sources_count": 1
        })
        yield mock


@pytest.fixture
def test_client(mock_db_repository, mock_redis):
    """Create test client with mocked dependencies."""
    from src.api.main import app
    return TestClient(app)


# Test data fixtures

@pytest.fixture
def valid_blog_request():
    """Valid blog generation request."""
    return {
        "user_id": "test_user_123",
        "topic": "The Future of Artificial Intelligence in Healthcare",
        "audience": "healthcare professionals"
    }


@pytest.fixture
def invalid_blog_request():
    """Invalid blog request (topic too short)."""
    return {
        "user_id": "test_user",
        "topic": "AI",  # Too short
        "audience": "anyone"
    }


@pytest.fixture
def approval_request():
    """Stage approval request."""
    return {
        "session_id": "test-session-123",
        "approved": True,
        "feedback": None
    }


@pytest.fixture
def rejection_request():
    """Stage rejection request."""
    return {
        "session_id": "test-session-123",
        "approved": False,
        "feedback": "Please focus more on specific examples"
    }
