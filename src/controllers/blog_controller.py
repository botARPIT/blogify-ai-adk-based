"""Blog generation controller - handles business logic for blog operations."""

import uuid
from typing import Any

from src.config.logging_config import get_logger
from src.guards.input_guard import input_guard
from src.guards.rate_limit_guard import rate_limit_guard
from src.models.repository import db_repository

logger = get_logger(__name__)


class BlogController:
    """Controller for blog generation business logic."""

    async def initiate_blog_generation(
        self, user_id: str, topic: str, audience: str | None
    ) -> dict[str, Any]:
        """
        Initiate blog generation with all validations and setup.
        
        Args:
            user_id: User identifier
            topic: Blog topic
            audience: Target audience
            
        Returns:
            Dictionary with session_id, status, and data
            
        Raises:
            ValueError: If validation fails
            RuntimeError: If rate limit exceeded
        """
        # Rate limiting
        allowed, msg = await rate_limit_guard.check_all_limits(user_id, is_blog_request=True)
        if not allowed:
            raise RuntimeError(msg)

        # Input validation
        valid, msg = input_guard.validate_input(topic, audience)
        if not valid:
            raise ValueError(msg)

        # Ensure user exists
        await db_repository.get_or_create_user(user_id)

        # Create session
        session_id = str(uuid.uuid4())

        # Create blog record
        blog = await db_repository.create_blog(
            user_id=user_id,
            session_id=session_id,
            topic=topic,
            audience=audience,
        )

        logger.info(
            "blog_generation_initiated",
            user_id=user_id,
            session_id=session_id,
            blog_id=blog.id,
        )

        # Update rate limiters
        await rate_limit_guard.increment_global_blog_count()
        await rate_limit_guard.increment_user_blog_count(user_id)

        return {
            "session_id": session_id,
            "status": "initiated",
            "stage": "intent",
            "message": "Blog generation started. Intent clarification needed.",
            "data": {
                "topic": topic,
                "audience": audience,
                "blog_id": blog.id,
                "next_action": "Proceed to approve the intent or request modifications"
            },
        }

    async def handle_stage_approval(
        self, session_id: str, approved: bool, feedback: str | None
    ) -> dict[str, Any]:
        """
        Handle approval or rejection of a pipeline stage.
        
        Args:
            session_id: Blog session identifier
            approved: Whether the stage was approved
            feedback: Optional feedback if rejected
            
        Returns:
            Dictionary with approval status and next steps
        """
        from datetime import datetime

        logger.info("stage_approval", session_id=session_id, approved=approved)

        # In full implementation: query blog, determine stage, resume pipeline
        
        if approved:
            return {
                "session_id": session_id,
                "status": "approved",
                "stage": "continuing",
                "message": "Stage approved. Continuing generation.",
                "data": {
                    "approved": True,
                    "next_steps": [
                        "Research phase will begin",
                        "Content will be written",
                        "Editor will review the draft"
                    ],
                    "estimated_time": "2-3 minutes",
                    "approval_timestamp": datetime.utcnow().isoformat()
                }
            }
        else:
            return {
                "session_id": session_id,
                "status": "rejected",
                "stage": "awaiting_changes",
                "message": feedback or "Stage rejected. Please provide changes.",
                "data": {
                    "approved": False,
                    "feedback": feedback,
                    "rejection_timestamp": datetime.utcnow().isoformat(),
                    "action_required": "Please modify your request or provide additional guidance"
                }
            }

    async def get_blog_status(self, session_id: str) -> dict[str, Any]:
        """
        Get current status of a blog generation session.
        
        Args:
            session_id: Blog session identifier
            
        Returns:
            Dictionary with blog status details
            
        Raises:
            ValueError: If blog not found
        """
        blog = await db_repository.get_blog_by_session(session_id)
        
        if not blog:
            raise ValueError("Blog session not found")
        
        # Map status to current stage
        stage_map = {
            "in_progress": "research",
            "completed": "final_review",
            "failed": "error",
        }
        
        return {
            "session_id": session_id,
            "blog_id": blog.id,
            "status": blog.status,
            "current_stage": stage_map.get(blog.status, "unknown"),
            "message": f"Blog is currently {blog.status}",
            "topic": blog.topic,
            "audience": blog.audience,
            "word_count": blog.word_count,
            "sources_count": blog.sources_count,
            "total_cost_usd": float(blog.total_cost_usd) if blog.total_cost_usd else 0.0,
            "created_at": blog.created_at.isoformat() if blog.created_at else None,
            "completed_at": blog.completed_at.isoformat() if blog.completed_at else None,
        }


# Global instance
blog_controller = BlogController()
