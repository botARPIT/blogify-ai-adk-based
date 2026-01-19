"""Integration tests for HITL (Human-in-the-Loop) approval workflow."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import os

os.environ["ENVIRONMENT"] = "dev"


class TestHITLWorkflow:
    """Tests for the Human-in-the-Loop approval workflow."""

    @pytest.mark.asyncio
    async def test_blog_generation_initiates_at_intent_stage(self):
        """Test blog generation starts at intent stage and pauses."""
        with patch("src.models.repository.db_repository") as mock_repo, \
             patch("src.agents.pipeline.blog_pipeline") as mock_pipeline:
            
            # Setup mocks
            mock_repo.get_or_create_user = AsyncMock(return_value=MagicMock(id=1))
            mock_repo.create_blog = AsyncMock(return_value=MagicMock(id=1))
            mock_repo.update_blog_stage = AsyncMock()
            mock_pipeline.run_intent_stage = AsyncMock(return_value={
                "status": "CLEAR",
                "message": "Topic is clear",
                "topic": "Test Topic",
                "audience": "Test Audience"
            })
            
            # Import after patching
            from src.services.blog_service import BlogService
            
            service = BlogService()
            # Override the repository on the service instance for this test
            service_repo_patch = patch.object(service.pipeline, 'run_intent_stage', mock_pipeline.run_intent_stage)
            
            with patch("src.services.blog_service.db_repository", mock_repo):
                result = await service.create_blog_session(
                    user_id="test_user",
                    topic="AI in Healthcare for Modern Diagnostics",
                    audience="doctors"
                )
            
                # Verify we're at intent stage
                assert result["stage"] == "intent"
                assert "intent_result" in result

    @pytest.mark.asyncio
    async def test_rejection_captures_feedback(self):
        """Test rejecting a stage captures feedback."""
        with patch("src.models.repository.db_repository") as mock_repo:
            
            mock_blog = MagicMock()
            mock_blog.current_stage = "intent"
            mock_blog.stage_data = {"status": "CLEAR"}
            mock_repo.get_blog_by_session = AsyncMock(return_value=mock_blog)
            
            from src.services.blog_service import BlogService
            
            service = BlogService()
            
            with patch("src.services.blog_service.db_repository", mock_repo):
                result = await service.process_stage_approval(
                    session_id="test-session",
                    approved=False,
                    feedback="Please focus more on specific examples"
                )
            
                assert result["approved"] is False
                assert result["feedback"] == "Please focus more on specific examples"
                assert result["action"] == "awaiting_modifications"

    @pytest.mark.asyncio
    async def test_invalid_session_raises_error(self):
        """Test invalid session ID raises ValueError."""
        with patch("src.models.repository.db_repository") as mock_repo:
            
            mock_repo.get_blog_by_session = AsyncMock(return_value=None)
            
            from src.services.blog_service import BlogService
            
            service = BlogService()
            
            with patch("src.services.blog_service.db_repository", mock_repo):
                with pytest.raises(ValueError, match="not found"):
                    await service.process_stage_approval(
                        session_id="invalid-session",
                        approved=True,
                        feedback=None
                    )


class TestHITLApprovalFlow:
    """Tests for complete approval flow."""
    
    @pytest.mark.asyncio
    async def test_approval_from_intent_to_outline(self):
        """Test approving intent stage moves to outline."""
        with patch("src.models.repository.db_repository") as mock_repo, \
             patch("src.agents.pipeline.BlogGenerationPipeline.run_outline_stage") as mock_outline:
            
            mock_blog = MagicMock()
            mock_blog.current_stage = "intent"
            mock_blog.stage_data = {"status": "CLEAR", "topic": "Test"}
            mock_repo.get_blog_by_session = AsyncMock(return_value=mock_blog)
            mock_repo.update_blog_stage = AsyncMock()
            
            mock_outline.return_value = {
                "title": "Test Blog",
                "sections": [{"id": "intro"}],
                "estimated_total_words": 500
            }
            
            from src.services.blog_service import BlogService
            service = BlogService()
            
            with patch("src.services.blog_service.db_repository", mock_repo):
                result = await service.process_stage_approval(
                    session_id="test-session",
                    approved=True,
                    feedback=None
                )
            
                assert result["approved"] is True
                assert result["next_stage"] == "outline"
