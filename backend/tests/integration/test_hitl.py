"""Integration tests for HITL (Human-in-the-Loop) approval workflow with async pipeline."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import os

os.environ["ENVIRONMENT"] = "dev"


class TestHITLConfirmationFlow:
    """Tests for Human-in-the-Loop confirmation workflow."""

    @pytest.mark.asyncio
    async def test_outline_confirmation_request(self):
        """Test pipeline requests outline confirmation."""
        from src.agents.pipeline import review_generated_outline
        from google.adk.tools import ToolContext

        mock_tool_context = MagicMock(spec=ToolContext)
        mock_tool_context.state = {
            "topic": "AI in Healthcare",
            "audience": "doctors",
            "blog_outline": {
                "title": "AI in Modern Diagnostics",
                "sections": [
                    {"id": "intro", "heading": "Introduction", "goal": "Hook reader", "target_words": 200},
                    {"id": "body1", "heading": "Current AI Applications", "goal": "Provide context", "target_words": 500},
                ],
                "estimated_total_words": 1000,
            },
        }
        mock_tool_context.tool_confirmation = None

        with patch.object(mock_tool_context, "request_confirmation") as mock_confirm:
            result = await review_generated_outline(mock_tool_context)

            assert result["status"] == "awaiting_outline_review"
            assert result["outline"]["title"] == "AI in Modern Diagnostics"
            mock_confirm.assert_called_once()

            call_args = mock_confirm.call_args
            payload = call_args.kwargs.get("payload") or call_args[1].get("payload")
            assert payload["topic"] == "AI in Healthcare"
            assert payload["audience"] == "doctors"

    @pytest.mark.asyncio
    async def test_outline_approved_with_edits(self):
        """Test pipeline handles approved outline with edits."""
        from src.agents.pipeline import review_generated_outline
        from google.adk.tools import ToolContext

        mock_tool_context = MagicMock(spec=ToolContext)
        mock_tool_context.state = {
            "topic": "Test Topic",
            "audience": "Test Audience",
            "blog_outline": {
                "title": "Original Title",
                "sections": [{"id": "intro"}],
            },
        }
        mock_tool_context.tool_confirmation = MagicMock()
        mock_tool_context.tool_confirmation.confirmed = True
        mock_tool_context.tool_confirmation.payload = {
            "approved_outline": {
                "title": "Updated Title",
                "sections": [
                    {"id": "intro", "heading": "New Introduction"},
                    {"id": "body", "heading": "New Section"},
                ],
            },
            "feedback_text": "Add more sections and update the title",
        }

        result = await review_generated_outline(mock_tool_context)

        assert result["status"] == "outline_approved"
        assert mock_tool_context.state["approved_outline"]["title"] == "Updated Title"
        assert mock_tool_context.state["outline_feedback"] == "Add more sections and update the title"

    @pytest.mark.asyncio
    async def test_outline_rejected(self):
        """Test pipeline handles rejected outline."""
        from src.agents.pipeline import review_generated_outline
        from google.adk.tools import ToolContext

        mock_tool_context = MagicMock(spec=ToolContext)
        mock_tool_context.state = {
            "topic": "Test Topic",
            "blog_outline": {"title": "Test", "sections": []},
        }
        mock_tool_context.tool_confirmation = MagicMock()
        mock_tool_context.tool_confirmation.confirmed = False

        result = await review_generated_outline(mock_tool_context)

        assert "error" in result
        assert "rejected" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_run_pipeline_with_confirmation(self):
        """Test run_pipeline pauses for confirmation when outline is generated."""
        from src.agents.pipeline import run_pipeline, PipelineResult

        with patch("src.agents.pipeline.Runner.run_async") as mock_run:
            mock_runner = AsyncMock()
            mock_run.return_value = mock_runner

            result = await run_pipeline(
                session_id="test-session",
                user_id="test-user",
                topic="AI in Healthcare",
                audience="doctors",
            )

            assert isinstance(result, PipelineResult)
            mock_run.assert_called_once()


class TestConfirmationPayloadSchema:
    """Tests for confirmation payload schema."""

    @pytest.mark.asyncio
    async def test_payload_contains_response_schema(self):
        """Test confirmation payload contains proper response schema."""
        from src.agents.pipeline import review_generated_outline
        from google.adk.tools import ToolContext

        mock_tool_context = MagicMock(spec=ToolContext)
        mock_tool_context.state = {
            "topic": "Test",
            "blog_outline": {"title": "Test", "sections": []},
        }
        mock_tool_context.tool_confirmation = None

        with patch.object(mock_tool_context, "request_confirmation") as mock_confirm:
            await review_generated_outline(mock_tool_context)

            call_args = mock_confirm.call_args
            payload = call_args.kwargs.get("payload") or call_args[1].get("payload")

            assert "response_schema" in payload
            assert "approved_outline" in payload["response_schema"]
            assert "feedback_text" in payload["response_schema"]


class TestResumeWithConfirmation:
    """Tests for resuming pipeline with confirmation."""

    @pytest.mark.asyncio
    async def test_resume_pipeline_continues_from_checkpoint(self):
        """Test resume_pipeline continues from the confirmation point."""
        from src.agents.pipeline import resume_pipeline, PipelineResult

        with patch("src.agents.pipeline.Runner.run_async") as mock_run:
            mock_runner = AsyncMock()
            mock_run.return_value = mock_runner

            result = await resume_pipeline(
                session_id="test-session",
                user_id="test-user",
                invocation_id="test-invocation-123",
            )

            assert isinstance(result, PipelineResult)
            mock_run.assert_called_once()