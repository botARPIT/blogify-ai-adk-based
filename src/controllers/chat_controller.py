"""Chat controller - handles business logic for chat operations."""

import uuid
from typing import Any

from src.config.logging_config import get_logger
from src.guards.rate_limit_guard import rate_limit_guard
from src.models.repository import db_repository

logger = get_logger(__name__)


class ChatController:
    """Controller for chat business logic."""

    async def handle_chat_message(
        self, user_id: str, message: str, session_id: str | None
    ) -> dict[str, Any]:
        """
        Handle a chat message with blog keyword detection.
        
        Args:
            user_id: User identifier
            message: User's message
            session_id: Optional existing session ID
            
        Returns:
            Dictionary with response and blog_generation_initiated flag
            
        Raises:
            RuntimeError: If rate limit exceeded
        """
        # Rate limiting
        allowed, msg = await rate_limit_guard.check_all_limits(user_id, is_blog_request=False)
        if not allowed:
            raise RuntimeError(msg)

        # Ensure user exists
        await db_repository.get_or_create_user(user_id)

        # Generate or use existing session
        session_id = session_id or str(uuid.uuid4())

        logger.info("chat_request_received", user_id=user_id, session_id=session_id)

        # Detect blog generation intent
        message_lower = message.lower()
        blog_keywords = ["blog", "write", "generate", "create article"]
        blog_initiated = any(keyword in message_lower for keyword in blog_keywords)
        
        if blog_initiated:
            response_text = (
                "I can help you generate a blog! To proceed, please use the "
                "/api/blog/generate endpoint with your topic and target audience. "
                "I'll guide you through the process with human approval checkpoints."
            )
        else:
            # Simple conversational response
            response_text = f"I received your message: '{message}'. "
            response_text += "I'm a blog generation assistant. Ask me to create a blog or use /api/blog/generate!"

        return {
            "session_id": session_id,
            "response": response_text,
            "blog_generation_initiated": blog_initiated,
        }


# Global instance
chat_controller = ChatController()
