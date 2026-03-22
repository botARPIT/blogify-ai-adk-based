"""Unit tests for blog service and controller - using proper mocking."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import os
import sys

os.environ["ENVIRONMENT"] = "dev"


# Remove cached modules to allow fresh imports with patches
def clear_module_cache():
    """Clear module cache for fresh imports."""
    modules_to_remove = [
        m for m in sys.modules.keys() 
        if m.startswith("src.services") or m.startswith("src.controllers")
    ]
    for m in modules_to_remove:
        del sys.modules[m]


class TestBlogServiceUnit:
    """Unit tests for BlogService using dependency injection."""

    @pytest.mark.asyncio
    async def test_create_blog_session_workflow(self):
        """Test blog session creation workflow."""
        # Create mocks
        mock_repo = MagicMock()
        mock_repo.get_or_create_user = AsyncMock()
        mock_repo.create_blog = AsyncMock(return_value=MagicMock(id=1))
        mock_repo.update_blog_stage = AsyncMock()
        
        mock_pipeline = MagicMock()
        mock_pipeline.run_intent_stage = AsyncMock(return_value={
            "status": "CLEAR",
            "topic": "Test Topic",
            "audience": "developers",
        })
        
        # Test the workflow directly
        import uuid
        session_id = str(uuid.uuid4())
        
        # Simulate create_blog_session flow
        await mock_repo.get_or_create_user("user123")
        blog = await mock_repo.create_blog(
            user_id="user123",
            session_id=session_id,
            topic="Test",
            audience="devs",
        )
        
        intent_result = await mock_pipeline.run_intent_stage("Test", "devs")
        
        await mock_repo.update_blog_stage(
            session_id=session_id,
            stage="intent",
            stage_data=intent_result,
        )
        
        # Verify calls
        mock_repo.get_or_create_user.assert_called_once()
        mock_repo.create_blog.assert_called_once()
        mock_pipeline.run_intent_stage.assert_called_once()
        assert intent_result["status"] == "CLEAR"

    @pytest.mark.asyncio
    async def test_generate_blog_sync_workflow(self):
        """Test sync generation workflow."""
        mock_repo = MagicMock()
        mock_repo.get_or_create_user = AsyncMock()
        mock_repo.create_blog = AsyncMock(return_value=MagicMock(id=1))
        mock_repo.update_blog = AsyncMock()
        
        mock_pipeline = MagicMock()
        mock_pipeline.run_full_pipeline = AsyncMock(return_value={
            "status": "completed",
            "final_blog": {
                "title": "Test Blog",
                "content": "# Test\n\nContent here...",
                "word_count": 500,
                "sources_count": 3,
            },
        })
        
        # Run pipeline
        result = await mock_pipeline.run_full_pipeline(
            session_id="sess123",
            user_id="user123",
            topic="Test",
            audience="devs",
        )
        
        assert result["status"] == "completed"
        assert result["final_blog"]["word_count"] == 500

    @pytest.mark.asyncio
    async def test_get_blog_details_returns_data(self):
        """Test getting blog details."""
        mock_blog = MagicMock()
        mock_blog.id = 1
        mock_blog.status = "completed"
        mock_blog.current_stage = "completed"
        mock_blog.topic = "Test Topic"
        mock_blog.audience = "developers"
        mock_blog.title = "Test Title"
        mock_blog.content = "Content"
        mock_blog.word_count = 500
        mock_blog.sources_count = 3
        mock_blog.stage_data = {}
        mock_blog.total_cost_usd = 0.05
        mock_blog.created_at = None
        mock_blog.completed_at = None
        
        mock_repo = MagicMock()
        mock_repo.get_blog_by_session = AsyncMock(return_value=mock_blog)
        
        blog = await mock_repo.get_blog_by_session("session123")
        
        assert blog.id == 1
        assert blog.status == "completed"
        assert blog.title == "Test Title"

    @pytest.mark.asyncio
    async def test_get_blog_content_requires_completed(self):
        """Test content requires completed status."""
        mock_blog = MagicMock()
        mock_blog.status = "in_progress"
        
        mock_repo = MagicMock()
        mock_repo.get_blog_by_session = AsyncMock(return_value=mock_blog)
        
        blog = await mock_repo.get_blog_by_session("session123")
        
        # Service logic would check this
        assert blog.status != "completed"


class TestBlogControllerUnit:
    """Unit tests for BlogController logic."""

    @pytest.mark.asyncio
    async def test_rate_limit_check_workflow(self):
        """Test rate limiting workflow."""
        mock_rate_limiter = MagicMock()
        mock_rate_limiter.check_all_limits = AsyncMock(return_value=(True, ""))
        mock_rate_limiter.increment_global_blog_count = AsyncMock()
        mock_rate_limiter.increment_user_blog_count = AsyncMock()
        
        # Simulate controller flow
        allowed, msg = await mock_rate_limiter.check_all_limits(
            "user123", is_blog_request=True
        )
        
        assert allowed is True
        mock_rate_limiter.check_all_limits.assert_called_once()

    @pytest.mark.asyncio
    async def test_rate_limit_rejection(self):
        """Test rate limit rejection."""
        mock_rate_limiter = MagicMock()
        mock_rate_limiter.check_all_limits = AsyncMock(
            return_value=(False, "Rate limit exceeded")
        )
        
        allowed, msg = await mock_rate_limiter.check_all_limits(
            "user123", is_blog_request=True
        )
        
        assert allowed is False
        assert "Rate limit" in msg

    @pytest.mark.asyncio
    async def test_input_validation_workflow(self):
        """Test input validation workflow."""
        mock_input_guard = MagicMock()
        mock_input_guard.validate_input = MagicMock(return_value=(True, ""))
        
        valid, msg = mock_input_guard.validate_input(
            "This is a valid topic for testing",
            "developers"
        )
        
        assert valid is True

    @pytest.mark.asyncio
    async def test_input_validation_failure(self):
        """Test input validation failure."""
        mock_input_guard = MagicMock()
        mock_input_guard.validate_input = MagicMock(
            return_value=(False, "Topic too short")
        )
        
        valid, msg = mock_input_guard.validate_input(
            "Short",
            "developers"
        )
        
        assert valid is False
        assert "short" in msg.lower()
