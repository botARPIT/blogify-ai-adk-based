"""Blog generation API routes - handles HTTP requests/responses only."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.config.logging_config import get_logger
from src.controllers.blog_controller import blog_controller

logger = get_logger(__name__)

router = APIRouter()


class BlogGenerationRequest(BaseModel):
    """Blog generation request model."""

    user_id: str = Field(..., description="User identifier")
    topic: str = Field(..., min_length=10, max_length=500, description="Blog topic")
    audience: str | None = Field(None, max_length=200, description="Target audience")


class ApprovalRequest(BaseModel):
    """Approval request model."""

    session_id: str = Field(..., description="Blog session ID")
    approved: bool = Field(..., description="Whether stage is approved")
    feedback: str | None = Field(None, description="Optional feedback if not approved")


class BlogGenerationResponse(BaseModel):
    """Blog generation response model."""

    session_id: str
    status: str
    stage: str | None = None
    message: str
    data: dict | None = None


@router.post("/blog/generate", response_model=BlogGenerationResponse)
async def generate_blog(request: BlogGenerationRequest):
    """
    Initiate blog generation.
    
    Delegates to blog_controller for business logic.
    """
    try:
        result = await blog_controller.initiate_blog_generation(
            user_id=request.user_id,
            topic=request.topic,
            audience=request.audience
        )
        return BlogGenerationResponse(**result)
    
    except RuntimeError as e:
        # Rate limit error
        raise HTTPException(status_code=429, detail=str(e))
    except ValueError as e:
        # Validation error
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("blog_generation_failed", error=str(e))
        raise HTTPException(status_code=500, detail="Blog generation failed")


@router.post("/blog/approve", response_model=BlogGenerationResponse)
async def approve_stage(request: ApprovalRequest):
    """
    Approve or reject a pipeline stage.
    
    Delegates to blog_controller for business logic.
    """
    try:
        result = await blog_controller.handle_stage_approval(
            session_id=request.session_id,
            approved=request.approved,
            feedback=request.feedback
        )
        return BlogGenerationResponse(**result)
    
    except Exception as e:
        logger.error("approval_failed", error=str(e))
        raise HTTPException(status_code=500, detail="Approval processing failed")


@router.get("/blog/status/{session_id}")
async def get_blog_status(session_id: str):
    """
    Get current status of a blog generation session.
    
    Delegates to blog_controller for business logic.
    """
    try:
        return await blog_controller.get_blog_status(session_id)
    
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("status_check_failed", error=str(e))
        raise HTTPException(status_code=500, detail="Status check failed")
