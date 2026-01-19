"""Chat service - handles ADK chatbot agent logic."""

import uuid
from typing import Any

from src.agents.chatbot_agent import chatbot_agent
from src.config.logging_config import get_logger
from src.models.repository import db_repository

logger = get_logger(__name__)


class ChatService:
    """Service layer for chat with ADK chatbot agent."""

    def __init__(self):
        self.chatbot = chatbot_agent

    async def process_message(
        self, user_id: str, message: str, session_id: str | None
    ) -> dict[str, Any]:
        """
        Process chat message using ADK chatbot agent.
        
        This is where the actual ADK chatbot_agent.run() would be called.
        
        Args:
            user_id: User identifier
            message: User's message
            session_id: Optional session ID
            
        Returns:
            Dictionary with response and metadata
        """
        # Ensure user exists
        await db_repository.get_or_create_user(user_id)

        # Generate or use session
        session_id = session_id or str(uuid.uuid4())

        logger.info("processing_chat_message", user_id=user_id, session_id=session_id)

        # In full implementation, invoke ADK chatbot:
        # result = await self.chatbot.run(
        #     state={"user_id": user_id, "message": message, "session_id": session_id}
        # )
        
        # For now, simple keyword detection
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
            response_text = (
                f"I received your message: '{message}'. "
                "I'm a blog generation assistant. Ask me to create a blog or use /api/blog/generate!"
            )

        return {
            "session_id": session_id,
            "response": response_text,
            "blog_generation_initiated": blog_initiated,
        }


# Global instance
chat_service = ChatService()
