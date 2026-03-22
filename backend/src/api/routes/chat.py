"""Chat API routes - handles HTTP requests/responses only."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.config.logging_config import get_logger
from src.controllers.chat_controller import chat_controller

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
    
    Delegates to chat_controller for business logic.
    """
    try:
        result = await chat_controller.handle_chat_message(
            user_id=request.user_id,
            message=request.message,
            session_id=request.session_id
        )
        return ChatResponse(**result)
    
    except RuntimeError as e:
        # Rate limit error
        raise HTTPException(status_code=429, detail=str(e))
    except Exception as e:
        logger.error("chat_request_failed", error=str(e), user_id=request.user_id)
        raise HTTPException(status_code=500, detail="Chat request failed")
