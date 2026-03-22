"""Integration tests for the blog generation pipeline."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import os

os.environ["ENVIRONMENT"] = "dev"



class TestBlogPipeline:
    """Tests for the blog generation pipeline."""

    @pytest.mark.asyncio
    async def test_intent_stage_returns_classification(self):
        """Test intent stage returns proper classification."""
        from src.agents.pipeline import BlogGenerationPipeline
        
        with patch.object(BlogGenerationPipeline, "_run_agent") as mock_agent:
            mock_agent.return_value = '{"status": "CLEAR", "message": "Topic is clear"}'
            
            pipeline = BlogGenerationPipeline()
            result = await pipeline.run_intent_stage(
                topic="AI in Healthcare",
                audience="doctors"
            )
            
            assert "status" in result
            assert "topic" in result
            assert result["topic"] == "AI in Healthcare"

    @pytest.mark.asyncio
    async def test_outline_stage_returns_structure(self):
        """Test outline stage returns proper structure."""
        from src.agents.pipeline import BlogGenerationPipeline
        
        with patch.object(BlogGenerationPipeline, "_run_agent") as mock_agent:
            mock_agent.return_value = '{"title": "Test Blog", "sections": [{"id": "intro"}], "estimated_total_words": 500}'
            
            pipeline = BlogGenerationPipeline()
            result = await pipeline.run_outline_stage({
                "topic": "Test Topic",
                "audience": "testers"
            })
            
            assert "title" in result
            assert "sections" in result
            assert isinstance(result["sections"], list)

    @pytest.mark.asyncio
    async def test_research_stage_calls_tavily(self):
        """Test research stage calls Tavily API."""
        from src.agents.pipeline import BlogGenerationPipeline
        
        with patch("src.agents.pipeline.research_topic") as mock_research:
            mock_research.return_value = {
                "topic": "Test",
                "summary": "Summary",
                "sources": [{"title": "Source 1", "url": "https://example.com"}],
                "total_sources": 1
            }
            
            pipeline = BlogGenerationPipeline()
            result = await pipeline.run_research_stage({
                "title": "Test Blog",
                "topic": "Machine Learning"
            })
            
            assert "sources" in result
            assert mock_research.called

    @pytest.mark.asyncio
    async def test_writing_stage_generates_content(self):
        """Test writing stage generates blog content."""
        from src.agents.pipeline import BlogGenerationPipeline
        
        with patch.object(BlogGenerationPipeline, "_run_agent") as mock_agent:
            mock_agent.return_value = "# Test Blog\n\nThis is the generated content..."
            
            pipeline = BlogGenerationPipeline()
            result = await pipeline.run_writing_stage(
                outline={
                    "title": "Test Blog",
                    "sections": [{"id": "intro", "heading": "Introduction", "goal": "Hook reader", "target_words": 200}],
                    "topic": "Test",
                    "audience": "testers"
                },
                research_data={
                    "sources": [{"title": "Source", "url": "https://example.com", "content": "Info"}]
                }
            )
            
            assert "title" in result
            assert "content" in result
            assert "word_count" in result

    @pytest.mark.asyncio
    async def test_full_pipeline_execution(self):
        """Test full pipeline runs all stages."""
        from src.agents.pipeline import BlogGenerationPipeline
        
        with patch.object(BlogGenerationPipeline, "_run_agent") as mock_agent, \
             patch("src.agents.pipeline.research_topic") as mock_research:
            
            mock_agent.return_value = '{"status": "CLEAR"}'
            mock_research.return_value = {
                "topic": "Test",
                "summary": "Summary",
                "sources": [],
                "total_sources": 0
            }
            
            pipeline = BlogGenerationPipeline()
            result = await pipeline.run_full_pipeline(
                session_id="test-session",
                user_id="test-user",
                topic="AI in Healthcare",
                audience="doctors"
            )
            
            assert result["status"] == "completed"
            assert "intent_result" in result
            assert "outline" in result
            assert "research_data" in result
            assert "final_blog" in result

    @pytest.mark.asyncio
    async def test_pipeline_handles_agent_failure(self):
        """Test pipeline handles agent failures gracefully."""
        from src.agents.pipeline import BlogGenerationPipeline
        
        with patch.object(BlogGenerationPipeline, "_run_agent") as mock_agent:
            mock_agent.side_effect = Exception("Agent failed")
            
            pipeline = BlogGenerationPipeline()
            result = await pipeline.run_intent_stage(
                topic="Test Topic",
                audience="testers"
            )
            
            # Should return fallback result
            assert "status" in result
            assert "topic" in result


class TestPipelineStageTransitions:
    """Tests for pipeline stage transitions."""

    @pytest.mark.asyncio
    async def test_intent_must_precede_outline(self):
        """Test intent stage must complete before outline."""
        # This is enforced by the service layer
        from src.services.blog_service import BlogService
        
        with patch("src.services.blog_service.db_repository") as mock_repo, \
             patch("src.services.blog_service.blog_pipeline") as mock_pipeline:
            
            mock_blog = MagicMock()
            mock_blog.current_stage = "intent"
            mock_blog.stage_data = {"status": "CLEAR"}
            mock_repo.get_blog_by_session = AsyncMock(return_value=mock_blog)
            mock_repo.update_blog_stage = AsyncMock()
            mock_pipeline.run_outline_stage = AsyncMock(return_value={"title": "Test"})
            
            service = BlogService()
            result = await service.process_stage_approval(
                session_id="test",
                approved=True,
                feedback=None
            )
            
            # Should transition to outline
            assert result["next_stage"] == "outline"

    @pytest.mark.asyncio
    async def test_outline_approval_triggers_research_and_writing(self):
        """Test outline approval runs research and writing automatically."""
        from src.services.blog_service import BlogService
        
        with patch("src.services.blog_service.db_repository") as mock_repo, \
             patch("src.services.blog_service.blog_pipeline") as mock_pipeline:
            
            mock_blog = MagicMock()
            mock_blog.current_stage = "outline"
            mock_blog.stage_data = {"title": "Test", "sections": []}
            mock_repo.get_blog_by_session = AsyncMock(return_value=mock_blog)
            mock_repo.update_blog = AsyncMock()
            
            mock_pipeline.run_research_stage = AsyncMock(return_value={"sources": []})
            mock_pipeline.run_writing_stage = AsyncMock(return_value={
                "title": "Test",
                "content": "# Test",
                "word_count": 100,
                "sources_count": 0
            })
            
            service = BlogService()
            result = await service.process_stage_approval(
                session_id="test",
                approved=True,
                feedback=None
            )
            
            # Should complete blog
            assert result["next_stage"] == "completed"
            mock_pipeline.run_research_stage.assert_called_once()
            mock_pipeline.run_writing_stage.assert_called_once()
