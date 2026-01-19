"""Unit tests for blog service layer."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import os

os.environ["ENVIRONMENT"] = "dev"


class TestBlogService:
    """Tests for BlogService."""

    @pytest.mark.asyncio
    async def test_create_blog_session_returns_session_id(self):
        """Test blog session creation returns session_id."""
        with patch("src.services.blog_service.db_repository") as mock_repo, \
             patch("src.services.blog_service.blog_pipeline") as mock_pipeline:
            
            mock_repo.get_or_create_user = AsyncMock()
            mock_repo.create_blog = AsyncMock(return_value=MagicMock(id=1))
            mock_repo.update_blog_stage = AsyncMock()
            mock_pipeline.run_intent_stage = AsyncMock(return_value={
                "status": "CLEAR",
                "topic": "Test Topic",
                "audience": "developers",
            })
            
            from src.services.blog_service import BlogService
            service = BlogService()
            service.pipeline = mock_pipeline
            
            result = await service.create_blog_session(
                user_id="user123",
                topic="How to build microservices with Python",
                audience="developers",
            )
            
            assert "session_id" in result
            assert result["stage"] == "intent"
            assert "intent_result" in result

    @pytest.mark.asyncio
    async def test_generate_blog_sync_returns_complete_blog(self):
        """Test sync generation returns complete blog."""
        with patch("src.services.blog_service.db_repository") as mock_repo, \
             patch("src.services.blog_service.blog_pipeline") as mock_pipeline:
            
            mock_repo.get_or_create_user = AsyncMock()
            mock_repo.create_blog = AsyncMock(return_value=MagicMock(id=1))
            mock_repo.update_blog = AsyncMock()
            mock_pipeline.run_full_pipeline = AsyncMock(return_value={
                "status": "completed",
                "final_blog": {
                    "title": "Test Blog",
                    "content": "# Test\n\nContent here...",
                    "word_count": 500,
                    "sources_count": 3,
                },
            })
            
            from src.services.blog_service import BlogService
            service = BlogService()
            service.pipeline = mock_pipeline
            
            result = await service.generate_blog_sync(
                user_id="user123",
                topic="Test Topic for Blog Generation",
                audience="developers",
            )
            
            assert result["status"] == "completed"
            assert "session_id" in result

    @pytest.mark.asyncio
    async def test_get_blog_details_returns_data(self):
        """Test getting blog details."""
        with patch("src.services.blog_service.db_repository") as mock_repo:
            
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
            
            mock_repo.get_blog_by_session = AsyncMock(return_value=mock_blog)
            
            from src.services.blog_service import BlogService
            service = BlogService()
            
            result = await service.get_blog_details("session123")
            
            assert result["blog_id"] == 1
            assert result["status"] == "completed"
            assert result["title"] == "Test Title"

    @pytest.mark.asyncio
    async def test_get_blog_content_requires_completed_status(self):
        """Test getting content requires completed status."""
        with patch("src.services.blog_service.db_repository") as mock_repo:
            
            mock_blog = MagicMock()
            mock_blog.status = "in_progress"  # Not completed
            
            mock_repo.get_blog_by_session = AsyncMock(return_value=mock_blog)
            
            from src.services.blog_service import BlogService
            service = BlogService()
            
            with pytest.raises(ValueError, match="not completed"):
                await service.get_blog_content("session123")


class TestBlogController:
    """Tests for BlogController."""

    @pytest.mark.asyncio
    async def test_initiate_blog_generation_checks_rate_limit(self):
        """Test rate limiting is checked during generation."""
        with patch("src.controllers.blog_controller.rate_limit_guard") as mock_rate, \
             patch("src.controllers.blog_controller.input_guard") as mock_input, \
             patch("src.controllers.blog_controller.blog_service") as mock_service:
            
            mock_rate.check_all_limits = AsyncMock(return_value=(True, ""))
            mock_input.validate_input.return_value = (True, "")
            mock_service.create_blog_session = AsyncMock(return_value={
                "session_id": "abc",
                "stage": "intent",
            })
            
            from src.controllers.blog_controller import BlogController
            controller = BlogController()
            
            await controller.initiate_blog_generation(
                user_id="user123",
                topic="Test Topic for Generation",
                audience="developers",
            )
            
            mock_rate.check_all_limits.assert_called_once()

    @pytest.mark.asyncio
    async def test_initiate_raises_on_rate_limit(self):
        """Test rate limit rejection raises error."""
        with patch("src.controllers.blog_controller.rate_limit_guard") as mock_rate:
            
            mock_rate.check_all_limits = AsyncMock(
                return_value=(False, "Rate limit exceeded")
            )
            
            from src.controllers.blog_controller import BlogController
            controller = BlogController()
            
            with pytest.raises(RuntimeError, match="Rate limit"):
                await controller.initiate_blog_generation(
                    user_id="user123",
                    topic="Test Topic for Generation",
                    audience="developers",
                )
