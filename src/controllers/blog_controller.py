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
        Initiate blog generation with validation.
        
        Controller responsibilities:
        - Apply guards (rate limiting, input validation)
        - Call service layer
        - Format response
        """
        # Apply guards
        allowed, msg = await rate_limit_guard.check_all_limits(user_id, is_blog_request=True)
        if not allowed:
            raise RuntimeError(msg)

        valid, msg = input_guard.validate_input(topic, audience)
        if not valid:
            raise ValueError(msg)

        # Call service layer (where ADK logic lives)
        session_data = await self.service.create_blog_session(user_id, topic, audience)

        # Update rate limiters
        await rate_limit_guard.increment_global_blog_count()
        await rate_limit_guard.increment_user_blog_count(user_id)

        # Format response
        return {
            "session_id": session_data["session_id"],
            "status": "initiated",
            "stage": session_data["stage"],
            "message": "Blog generation started. Intent clarification needed.",
            "data": {
                "topic": session_data["topic"],
                "audience": session_data["audience"],
                "blog_id": session_data["blog_id"],
                "next_action": "Proceed to approve the intent or request modifications"
            },
        }

    async def handle_stage_approval(
        self, session_id: str, approved: bool, feedback: str | None
    ) -> dict[str, Any]:
        """
        Handle approval/rejection.
        
        Controller delegates to service for ADK pipeline continuation.
        """
        logger.info("stage_approval", session_id=session_id, approved=approved)

        # Call service layer (ADK pipeline logic)
        approval_result = await self.service.process_stage_approval(
            session_id, approved, feedback
        )

        # Format response
        if approved:
            return {
                "session_id": session_id,
                "status": "approved",
                "stage": "continuing",
                "message": "Stage approved. Continuing generation.",
                "data": {
                    **approval_result,
                    "next_steps": [
                        "Research phase will begin",
                        "Content will be written",
                        "Editor will review the draft"
                    ],
                    "estimated_time": "2-3 minutes",
                }
            }
        else:
            return {
                "session_id": session_id,
                "status": "rejected",
                "stage": "awaiting_changes",
                "message": feedback or "Stage rejected. Please provide changes.",
                "data": {
                    **approval_result,
                    "action_required": "Please modify your request or provide additional guidance"
                }
            }

    async def get_blog_status(self, session_id: str) -> dict[str, Any]:
        """
        Get blog status.
        
        Controller delegates to service.
        """
        # Call service layer
        return await self.service.get_blog_details(session_id)


# Global instance
blog_controller = BlogController()
