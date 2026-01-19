"""Blog generation service - handles ADK agent orchestration and business logic."""

import uuid
from typing import Any

from src.agents.pipeline import blog_pipeline
from src.config.logging_config import get_logger
from src.models.repository import db_repository

logger = get_logger(__name__)


class BlogService:
    """Service layer for blog generation with ADK agents."""

    def __init__(self):
        self.pipeline = blog_pipeline

    async def create_blog_session(
        self, user_id: str, topic: str, audience: str | None
    ) -> dict[str, Any]:
        """
        Create a new blog generation session.
        
        This is where ADK pipeline would be initiated in full implementation.
        
        Args:
            user_id: User identifier  
            topic: Blog topic
            audience: Target audience
            
        Returns:
            Dictionary with session details
        """
        # Ensure user exists
        await db_repository.get_or_create_user(user_id)

        # Create session ID
        session_id = str(uuid.uuid4())

        # Create blog record
        blog = await db_repository.create_blog(
            user_id=user_id,
            session_id=session_id,
            topic=topic,
            audience=audience,
        )

        logger.info(
            "blog_session_created",
            user_id=user_id,
            session_id=session_id,
            blog_id=blog.id,
        )

        # In full implementation, this would:
        # 1. Start async task for pipeline.run_with_approvals()
        # 2. Send to task queue (Celery/Cloud Tasks)
        # 3. Set up state for human approval workflow

        return {
            "session_id": session_id,
            "blog_id": blog.id,
            "topic": topic,
            "audience": audience,
            "stage": "intent",
        }

    async def process_stage_approval(
        self, session_id: str, approved: bool, feedback: str | None
    ) -> dict[str, Any]:
        """
        Process approval/rejection and continue ADK pipeline.
        
        This is where ADK agents would be invoked to continue generation.
        
        Args:
            session_id: Blog session ID
            approved: Whether approved
            feedback: Optional feedback
            
        Returns:
            Dictionary with next stage information  
        """
        from datetime import datetime

        logger.info("processing_approval", session_id=session_id, approved=approved)

        # Get blog from database
        blog = await db_repository.get_blog_by_session(session_id)
        if not blog:
            raise ValueError("Blog session not found")

        if approved:
            # In full implementation:
            # 1. Resume ADK pipeline from saved state
            # 2. Run next agent (outline/research/writer)
            # 3. Update blog status in DB
            
            return {
                "approved": True,
                "next_stage": "outline",  # Would be dynamic based on current stage
                "message": "Continuing to next stage",
                "timestamp": datetime.utcnow().isoformat()
            }
        else:
            # Handle rejection - would trigger agent re-run with feedback
            return {
                "approved": False,
                "feedback": feedback,
                "action": "awaiting_modifications",
                "timestamp": datetime.utcnow().isoformat()
            }

    async def get_blog_details(self, session_id: str) -> dict[str, Any]:
        """
        Get blog generation status and details.
        
        Args:
            session_id: Blog session ID
            
        Returns:
            Blog details dictionary
        """
        blog = await db_repository.get_blog_by_session(session_id)
        
        if not blog:
            raise ValueError("Blog session not found")
        
        # Determine current stage from status
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
            "topic": blog.topic,
            "audience": blog.audience,
            "word_count": blog.word_count,
            "sources_count": blog.sources_count,
            "total_cost_usd": float(blog.total_cost_usd) if blog.total_cost_usd else 0.0,
            "created_at": blog.created_at.isoformat() if blog.created_at else None,
            "completed_at": blog.completed_at.isoformat() if blog.completed_at else None,
        }


# Global instance
blog_service = BlogService()
