"""Integration tests for the async blog generation pipeline."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import os

os.environ["ENVIRONMENT"] = "dev"


class TestAsyncPipeline:
    """Tests for the async blog generation pipeline."""

    @pytest.mark.asyncio
    async def test_run_pipeline_returns_result(self):
        """Test run_pipeline returns a valid PipelineResult."""
        from src.agents.pipeline import run_pipeline, PipelineResult

        with patch("src.agents.pipeline.Runner.run_async") as mock_run:
            mock_run.return_value = AsyncMock()

            result = await run_pipeline(
                session_id="test-session",
                user_id="test-user",
                topic="AI in Healthcare",
                audience="doctors",
            )

            assert isinstance(result, PipelineResult)
            assert result.session_id == "test-session"

    @pytest.mark.asyncio
    async def test_resume_pipeline_returns_result(self):
        """Test resume_pipeline returns a valid PipelineResult."""
        from src.agents.pipeline import resume_pipeline, PipelineResult

        with patch("src.agents.pipeline.Runner.run_async") as mock_run:
            mock_run.return_value = AsyncMock()

            result = await resume_pipeline(
                session_id="test-session",
                user_id="test-user",
                invocation_id="test-invocation",
            )

            assert isinstance(result, PipelineResult)

    @pytest.mark.asyncio
    async def test_pipeline_handles_confirmation_request(self):
        """Test pipeline handles outline confirmation requests."""
        from src.agents.pipeline import review_generated_outline, PipelineResult
        from google.adk.tools import ToolContext

        mock_tool_context = MagicMock(spec=ToolContext)
        mock_tool_context.state = {
            "topic": "Test Topic",
            "audience": "Test Audience",
            "blog_outline": {
                "title": "Test Blog",
                "sections": [{"id": "intro", "heading": "Introduction"}],
            },
        }
        mock_tool_context.tool_confirmation = None

        with patch.object(mock_tool_context, "request_confirmation") as mock_confirm:
            result = await review_generated_outline(mock_tool_context)

            assert result["status"] == "awaiting_outline_review"
            assert "outline" in result
            mock_confirm.assert_called_once()

    @pytest.mark.asyncio
    async def test_pipeline_handles_approved_outline(self):
        """Test pipeline handles approved outline confirmation."""
        from src.agents.pipeline import review_generated_outline
        from google.adk.tools import ToolContext

        mock_tool_context = MagicMock(spec=ToolContext)
        mock_tool_context.state = {
            "topic": "Test Topic",
            "audience": "Test Audience",
            "blog_outline": {
                "title": "Test Blog",
                "sections": [{"id": "intro", "heading": "Introduction"}],
            },
        }
        mock_tool_context.tool_confirmation = MagicMock()
        mock_tool_context.tool_confirmation.confirmed = True
        mock_tool_context.tool_confirmation.payload = {
            "approved_outline": {
                "title": "Approved Blog",
                "sections": [{"id": "intro", "heading": "Introduction"}],
            },
            "feedback_text": "Good outline",
        }

        result = await review_generated_outline(mock_tool_context)

        assert result["status"] == "outline_approved"
        assert mock_tool_context.state["approved_outline"]["title"] == "Approved Blog"

    @pytest.mark.asyncio
    async def test_pipeline_handles_rejected_outline(self):
        """Test pipeline handles rejected outline confirmation."""
        from src.agents.pipeline import review_generated_outline
        from google.adk.tools import ToolContext

        mock_tool_context = MagicMock(spec=ToolContext)
        mock_tool_context.state = {
            "topic": "Test Topic",
            "blog_outline": {"title": "Test Blog", "sections": []},
        }
        mock_tool_context.tool_confirmation = MagicMock()
        mock_tool_context.tool_confirmation.confirmed = False
        mock_tool_context.tool_confirmation.payload = {}

        result = await review_generated_outline(mock_tool_context)

        assert result["status"] == "outline_approved"
        assert "error" not in result


class TestPipelineCostTracking:
    """Tests for pipeline cost tracking."""

    @pytest.mark.asyncio
    async def test_pipeline_result_contains_cost_info(self):
        """Test PipelineResult includes cost information."""
        from src.agents.pipeline import PipelineResult, CostInfo

        result = PipelineResult(
            session_id="test-session",
            costs=[
                CostInfo(
                    stage="intent",
                    model="gemini-2.0-flash",
                    prompt_tokens=100,
                    completion_tokens=50,
                    total_tokens=150,
                ),
            ],
        )

        assert len(result.costs) == 1
        assert result.costs[0].stage == "intent"
        assert result.costs[0].total_tokens == 150


class TestPipelineErrorHandling:
    """Tests for pipeline error handling."""

    @pytest.mark.asyncio
    async def test_pipeline_returns_error_on_exception(self):
        """Test pipeline returns error when exception occurs."""
        from src.agents.pipeline import run_pipeline

        with patch("src.agents.pipeline.Runner.run_async") as mock_run:
            mock_run.side_effect = Exception("LLM API error")

            result = await run_pipeline(
                session_id="test-session",
                user_id="test-user",
                topic="Test Topic",
            )

            assert result.error is not None
            assert "LLM API error" in result.error

    @pytest.mark.asyncio
    async def test_pipeline_pause_for_confirmation(self):
        """Test pipeline pauses when confirmation is requested."""
        from src.agents.pipeline import run_pipeline, PipelineResult

        with patch("src.agents.pipeline.Runner.run_async") as mock_run:
            mock_run.return_value = AsyncMock()

            result = await run_pipeline(
                session_id="test-session",
                user_id="test-user",
                topic="Test Topic",
            )

            assert isinstance(result, PipelineResult)