"""Blog generation service — DEPRECATED.

.. deprecated::
    This module contains sync LLM-in-HTTP HITL flows that have been
    replaced by the ADK-native pipeline in ``src.agents.pipeline_v2``
    (SequentialAgent + LoopAgent + LongRunningFunctionTool).
    All new code should use ``pipeline_v2.run_pipeline()``.
"""

import warnings
warnings.warn(
    "blog_service is deprecated; use src.agents.pipeline_v2 instead",
    DeprecationWarning,
    stacklevel=2,
)

import uuid
from datetime import datetime
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
        Create a new blog generation session and run intent stage.
        
        Args:
            user_id: User identifier  
            topic: Blog topic
            audience: Target audience
            
        Returns:
            Dict with session details and intent result
        """
        # Ensure user exists
        await db_repository.get_or_create_user(user_id)

        # Create session ID
        session_id = str(uuid.uuid4())
        audience = audience or "general readers"

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

        # Run intent classification stage
        intent_result = await self.pipeline.run_intent_stage(topic, audience)
        
        # Save intent result to database
        await db_repository.update_blog_stage(
            session_id=session_id,
            stage="intent",
            stage_data=intent_result,
        )

        return {
            "session_id": session_id,
            "blog_id": blog.id,
            "topic": topic,
            "audience": audience,
            "stage": "intent",
            "intent_result": intent_result,
        }

    async def process_stage_approval(
        self, session_id: str, approved: bool, feedback: str | None
    ) -> dict[str, Any]:
        """
        Process approval and continue to next pipeline stage.
        
        Args:
            session_id: Blog session ID
            approved: Whether approved
            feedback: Optional feedback for rejection
            
        Returns:
            Next stage information
        """
        logger.info("processing_approval", session_id=session_id, approved=approved)

        # Get blog from database
        blog = await db_repository.get_blog_by_session(session_id)
        if not blog:
            raise ValueError("Blog session not found")

        current_stage = blog.current_stage or "intent"
        stage_data = blog.stage_data or {}

        if not approved:
            return {
                "approved": False,
                "feedback": feedback,
                "action": "awaiting_modifications",
                "current_stage": current_stage,
                "timestamp": datetime.utcnow().isoformat()
            }

        # Progress to next stage based on current stage
        if current_stage == "intent":
            # Run outline stage
            outline_result = await self.pipeline.run_outline_stage(stage_data)
            
            await db_repository.update_blog_stage(
                session_id=session_id,
                stage="outline",
                stage_data=outline_result,
            )
            
            return {
                "approved": True,
                "next_stage": "outline",
                "stage_data": outline_result,
                "message": "Intent approved. Outline generated.",
                "timestamp": datetime.utcnow().isoformat()
            }
            
        elif current_stage == "outline":
            # Run research and writing (auto, no pause)
            outline = stage_data
            
            # Research
            research_data = await self.pipeline.run_research_stage(outline)
            
            # Writing
            final_blog = await self.pipeline.run_writing_stage(outline, research_data)
            
            # Update blog with final content
            await db_repository.update_blog(
                session_id=session_id,
                title=final_blog.get("title"),
                content=final_blog.get("content"),
                word_count=final_blog.get("word_count", 0),
                sources_count=final_blog.get("sources_count", 0),
                status="completed",
            )
            
            return {
                "approved": True,
                "next_stage": "completed",
                "final_blog": final_blog,
                "message": "Blog generation completed!",
                "timestamp": datetime.utcnow().isoformat()
            }
        
        else:
            return {
                "approved": True,
                "next_stage": "unknown",
                "message": f"Unknown stage: {current_stage}",
                "timestamp": datetime.utcnow().isoformat()
            }

    async def generate_blog_sync(
        self, user_id: str, topic: str, audience: str | None
    ) -> dict[str, Any]:
        """
        Generate blog synchronously without HITL pauses.
        
        For testing or when approvals are pre-authorized.
        
        Args:
            user_id: User identifier
            topic: Blog topic
            audience: Target audience
            
        Returns:
            Complete blog with all stages
        """
        # Ensure user exists
        await db_repository.get_or_create_user(user_id)

        session_id = str(uuid.uuid4())
        audience = audience or "general readers"

        # Create blog record
        blog = await db_repository.create_blog(
            user_id=user_id,
            session_id=session_id,
            topic=topic,
            audience=audience,
        )

        logger.info("sync_generation_started", session_id=session_id)

        # Run full pipeline
        result = await self.pipeline.run_full_pipeline(
            session_id=session_id,
            user_id=user_id,
            topic=topic,
            audience=audience,
        )

        final_blog = result.get("final_blog", {})

        # Update blog with final content
        await db_repository.update_blog(
            session_id=session_id,
            title=final_blog.get("title"),
            content=final_blog.get("content"),
            word_count=final_blog.get("word_count", 0),
            sources_count=final_blog.get("sources_count", 0),
            status="completed",
        )

        logger.info("sync_generation_completed", session_id=session_id)

        return {
            "session_id": session_id,
            "blog_id": blog.id,
            "status": "completed",
            **result
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
        
        return {
            "session_id": session_id,
            "blog_id": blog.id,
            "status": blog.status,
            "current_stage": blog.current_stage or "initiated",
            "topic": blog.topic,
            "audience": blog.audience,
            "title": blog.title,
            "content": blog.content,
            "word_count": blog.word_count,
            "sources_count": blog.sources_count,
            "stage_data": blog.stage_data,
            "total_cost_usd": float(blog.total_cost_usd) if blog.total_cost_usd else 0.0,
            "created_at": blog.created_at.isoformat() if blog.created_at else None,
            "completed_at": blog.completed_at.isoformat() if blog.completed_at else None,
        }

    async def get_blog_content(self, session_id: str) -> dict[str, Any]:
        """
        Get the final generated blog content.
        
        Args:
            session_id: Blog session ID
            
        Returns:
            Blog content or error
        """
        blog = await db_repository.get_blog_by_session(session_id)
        
        if not blog:
            raise ValueError("Blog session not found")
        
        if blog.status != "completed":
            raise ValueError(f"Blog not completed. Status: {blog.status}")
        
        return {
            "session_id": session_id,
            "title": blog.title,
            "content": blog.content,
            "word_count": blog.word_count,
            "sources_count": blog.sources_count,
            "topic": blog.topic,
            "audience": blog.audience,
            "completed_at": blog.completed_at.isoformat() if blog.completed_at else None,
        }


# Global instance
blog_service = BlogService()
