"""Chat controller - orchestrates requests and responses."""

from typing import Any

from src.config.logging_config import get_logger
from src.guards.rate_limit_guard import rate_limit_guard
from src.services.chat_service import chat_service

logger = get_logger(__name__)


class ChatController:
    """Controller for chat operations - orchestrates guards and service calls."""

    def __init__(self):
        self.service = chat_service

    async def handle_chat_message(
        self, user_id: str, message: str, session_id: str | None
    ) -> dict[str, Any]:
        """
        Handle chat message.
        
        Controller responsibilities:
        - Apply guards (rate limiting)
        - Call service layer (ADK chatbot logic)
        - Format response
        """
        # Apply guards
        allowed, msg = await rate_limit_guard.check_all_limits(user_id, is_blog_request=False)
        if not allowed:
            raise RuntimeError(msg)

        # Call service layer (where ADK chatbot lives)
        return await self.service.process_message(user_id, message, session_id)


# Global instance
chat_controller = ChatController()
