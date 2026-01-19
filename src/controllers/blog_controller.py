"""Blog generation controller - orchestrates requests and responses."""

from typing import Any

from src.config.logging_config import get_logger
from src.guards.input_guard import input_guard
from src.guards.rate_limit_guard import rate_limit_guard
from src.services.blog_service import blog_service

logger = get_logger(__name__)


class BlogController:
    """Controller for blog operations - orchestrates guards and service calls."""

    def __init__(self):
        self.service = blog_service

    async def initiate_blog_generation(
        self, user_id: str, topic: str, audience: str | None
    ) -> dict[str, Any]:
        """
        Initiate blog generation with HITL approvals.
        
        Runs intent stage and pauses for approval.
        """
        # Apply guards
        allowed, msg = await rate_limit_guard.check_all_limits(user_id, is_blog_request=True)
        if not allowed:
            raise RuntimeError(msg)

        valid, msg = input_guard.validate_input(topic, audience)
        if not valid:
            raise ValueError(msg)

        # Call service layer
        session_data = await self.service.create_blog_session(user_id, topic, audience)

        # Update rate limiters
        await rate_limit_guard.increment_global_blog_count()
        await rate_limit_guard.increment_user_blog_count(user_id)

        # Format response
        return {
            "session_id": session_data["session_id"],
            "status": "initiated",
            "stage": session_data["stage"],
            "message": "Blog generation started. Intent clarification complete - approve to continue.",
            "data": {
                "topic": session_data["topic"],
                "audience": session_data["audience"],
                "blog_id": session_data["blog_id"],
                "intent_result": session_data.get("intent_result"),
                "next_action": "Review intent and approve to generate outline"
            },
        }

    async def generate_blog_sync(
        self, user_id: str, topic: str, audience: str | None
    ) -> dict[str, Any]:
        """
        Generate blog synchronously without approval pauses.
        """
        # Apply guards
        allowed, msg = await rate_limit_guard.check_all_limits(user_id, is_blog_request=True)
        if not allowed:
            raise RuntimeError(msg)

        valid, msg = input_guard.validate_input(topic, audience)
        if not valid:
            raise ValueError(msg)

        # Call service layer for sync generation
        result = await self.service.generate_blog_sync(user_id, topic, audience)

        # Update rate limiters
        await rate_limit_guard.increment_global_blog_count()
        await rate_limit_guard.increment_user_blog_count(user_id)

        final_blog = result.get("final_blog", {})

        return {
            "session_id": result["session_id"],
            "status": "completed",
            "stage": "final",
            "message": "Blog generated successfully!",
            "data": {
                "blog_id": result["blog_id"],
                "title": final_blog.get("title"),
                "word_count": final_blog.get("word_count"),
                "sources_count": final_blog.get("sources_count"),
                "content_preview": final_blog.get("content", "")[:500] + "..."
            },
        }

    async def handle_stage_approval(
        self, session_id: str, approved: bool, feedback: str | None
    ) -> dict[str, Any]:
        """
        Handle approval/rejection and continue pipeline.
        """
        logger.info("stage_approval", session_id=session_id, approved=approved)

        # Call service layer
        approval_result = await self.service.process_stage_approval(
            session_id, approved, feedback
        )

        # Format response
        if approved:
            next_stage = approval_result.get("next_stage", "unknown")
            
            if next_stage == "completed":
                final_blog = approval_result.get("final_blog", {})
                return {
                    "session_id": session_id,
                    "status": "completed",
                    "stage": "final",
                    "message": "Blog generation completed!",
                    "data": {
                        "title": final_blog.get("title"),
                        "word_count": final_blog.get("word_count"),
                        "sources_count": final_blog.get("sources_count"),
                        "content_preview": final_blog.get("content", "")[:500] + "...",
                        "next_action": "Use /blog/content/{session_id} to get full content"
                    }
                }
            else:
                return {
                    "session_id": session_id,
                    "status": "approved",
                    "stage": next_stage,
                    "message": f"Stage approved. Moved to {next_stage} stage.",
                    "data": {
                        "stage_data": approval_result.get("stage_data"),
                        "next_action": f"Review {next_stage} and approve to continue"
                    }
                }
        else:
            return {
                "session_id": session_id,
                "status": "rejected",
                "stage": approval_result.get("current_stage"),
                "message": feedback or "Stage rejected. Please provide changes.",
                "data": {
                    "feedback": feedback,
                    "action_required": "Modify your request or provide additional guidance"
                }
            }

    async def get_blog_status(self, session_id: str) -> dict[str, Any]:
        """Get blog status."""
        return await self.service.get_blog_details(session_id)

    async def get_blog_content(self, session_id: str) -> dict[str, Any]:
        """Get final blog content."""
        return await self.service.get_blog_content(session_id)


# Global instance
blog_controller = BlogController()
