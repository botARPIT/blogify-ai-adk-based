"""Blog generation controller - orchestrates requests and responses."""

import uuid
from typing import Any

from src.config.logging_config import get_logger
from src.core.task_queue import enqueue_blog_generation
from src.guards.input_guard import input_guard
from src.guards.rate_limit_guard import rate_limit_guard
from src.models.repository import db_repository

logger = get_logger(__name__)


class BlogController:
    """Compatibility wrapper around the async queue-based blog workflow."""

    async def initiate_blog_generation(
        self, user_id: str, topic: str, audience: str | None
    ) -> dict[str, Any]:
        """
        Initiate async blog generation through the worker queue.
        """
        allowed, msg = await rate_limit_guard.check_all_limits(user_id, is_blog_request=True)
        if not allowed:
            raise RuntimeError(msg)

        valid, msg = input_guard.validate_input(topic, audience)
        if not valid:
            raise ValueError(msg)

        session_id = str(uuid.uuid4())
        await db_repository.get_or_create_user(user_id)
        blog = await db_repository.create_blog(
            user_id=user_id,
            session_id=session_id,
            topic=topic,
            audience=audience or "general readers",
        )
        task_id = await enqueue_blog_generation(
            user_id=user_id,
            topic=topic,
            audience=audience,
            session_id=session_id,
            blog_id=blog.id,
        )

        await rate_limit_guard.increment_global_blog_count()
        await rate_limit_guard.increment_user_blog_count(user_id)

        return {
            "session_id": session_id,
            "status": "queued",
            "stage": "pending",
            "message": "Blog generation queued. Poll task or session status endpoints for updates.",
            "data": {
                "topic": topic,
                "audience": audience or "general readers",
                "blog_id": blog.id,
                "task_id": task_id,
                "next_action": "Poll task status until the blog is completed",
            },
        }

    async def generate_blog_sync(
        self, user_id: str, topic: str, audience: str | None
    ) -> dict[str, Any]:
        """
        Queue blog generation and return the task metadata.
        """
        return await self.initiate_blog_generation(user_id, topic, audience)

    async def handle_stage_approval(
        self, session_id: str, approved: bool, feedback: str | None
    ) -> dict[str, Any]:
        """
        Legacy approval path is no longer supported.
        """
        logger.warning("legacy_stage_approval_called", session_id=session_id, approved=approved)
        raise RuntimeError("HITL approval workflow is deprecated in the legacy controller")

    async def get_blog_status(self, session_id: str) -> dict[str, Any]:
        """Get blog status."""
        blog = await db_repository.get_blog_by_session(session_id)
        if not blog:
            raise ValueError("Blog session not found")

        return {
            "session_id": session_id,
            "blog_id": blog.id,
            "status": blog.status,
            "stage": blog.current_stage,
            "title": blog.title,
            "word_count": blog.word_count,
        }

    async def get_blog_content(self, session_id: str) -> dict[str, Any]:
        """Get final blog content."""
        blog = await db_repository.get_blog_by_session(session_id)
        if not blog:
            raise ValueError("Blog session not found")
        if blog.status != "completed":
            raise ValueError(f"Blog not completed. Current status: {blog.status}")

        return {
            "session_id": session_id,
            "title": blog.title,
            "content": blog.content,
            "word_count": blog.word_count,
            "sources_count": blog.sources_count,
        }


# Global instance
blog_controller = BlogController()
