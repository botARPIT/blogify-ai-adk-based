"""Chat API endpoints."""

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.agents.chatbot_agent import chatbot_agent
from src.api.main import request_semaphore
from src.config.logging_config import get_logger
from src.guards.rate_limit_guard import rate_limit_guard
from src.models.repository import db_repository

logger = get_logger(__name__)

router = APIRouter()


class ChatRequest(BaseModel):
    """Chat request model."""

    user_id: str = Field(..., description="User identifier")
    message: str = Field(..., min_length=1, max_length=2000, description="User message")
    session_id: str | None = Field(None, description="Optional session ID for continuity")


class ChatResponse(BaseModel):
    """Chat response model."""

    session_id: str
    response: str
    blog_generation_initiated: bool = False


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    Chat with the AI assistant.
    
    The chatbot can answer general questions or initiate blog generation
    when explicitly requested by the user.
    """
    async with request_semaphore:
        # Rate limiting
        allowed, msg = await rate_limit_guard.check_all_limits(request.user_id, is_blog_request=False)
        if not allowed:
            raise HTTPException(status_code=429, detail=msg)

        # Ensure user exists
        await db_repository.get_or_create_user(request.user_id)

        # Generate or use existing session ID
        session_id = request.session_id or str(uuid.uuid4())

        logger.info(
            "chat_request_received",
            user_id=request.user_id,
            session_id=session_id,
        )

        try:
            # TODO: Invoke chatbot agent
            # For now, return a placeholder response
            
            response_text = f"Echo: {request.message}"
            blog_initiated = "blog" in request.message.lower() and "generate" in request.message.lower()

            return ChatResponse(
                session_id=session_id,
                response=response_text,
                blog_generation_initiated=blog_initiated,
            )

        except Exception as e:
            logger.error("chat_request_failed", error=str(e), user_id=request.user_id)
            raise HTTPException(status_code=500, detail="Chat request failed")
