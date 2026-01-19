"""Blog generation API endpoints."""

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.agents.pipeline import blog_pipeline
from src.config.logging_config import get_logger
from src.guards.input_guard import input_guard
from src.guards.output_guard import output_guard
from src.guards.rate_limit_guard import rate_limit_guard
from src.models.repository import db_repository

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
    status: str  # initiated, pending_approval, completed, failed
    stage: str | None = None  # intent, outline, research, writing
    message: str
    data: dict[str, Any] | None = None


@router.post("/blog/generate", response_model=BlogGenerationResponse)
async def generate_blog(request: BlogGenerationRequest):
    """
    Initiate blog generation.
    
    This will start the blog generation pipeline with human approval checkpoints.
    """
    # Rate limiting (blog-specific)
    allowed, msg = await rate_limit_guard.check_all_limits(request.user_id, is_blog_request=True)
    if not allowed:
        raise HTTPException(status_code=429, detail=msg)

    # Input guardrail
    valid, msg = input_guard.validate_input(request.topic, request.audience)
    if not valid:
        raise HTTPException(status_code=400, detail=msg)

    # Ensure user exists
    await db_repository.get_or_create_user(request.user_id)

    # Create session
    session_id = str(uuid.uuid4())

    # Create blog record
    blog = await db_repository.create_blog(
        user_id=request.user_id,
        session_id=session_id,
        topic=request.topic,
        audience=request.audience,
    )

    logger.info(
        "blog_generation_initiated",
        user_id=request.user_id,
        session_id=session_id,
        blog_id=blog.id,
    )

    # Increment rate limiters
    await rate_limit_guard.increment_global_blog_count()
    await rate_limit_guard.increment_user_blog_count(request.user_id)

    try:
        # TODO: Start blog pipeline
        # result = await blog_pipeline.run_with_approvals(...)

        return BlogGenerationResponse(
            session_id=session_id,
            status="initiated",
            stage="intent",
            message="Blog generation started. Awaiting intent clarification.",
            data={"topic": request.topic, "audience": request.audience},
        )

    except Exception as e:
        logger.error("blog_generation_failed", error=str(e), session_id=session_id)
        await db_repository.update_blog(session_id, status="failed")
        raise HTTPException(status_code=500, detail="Blog generation failed")


@router.post("/blog/approve", response_model=BlogGenerationResponse)
async def approve_stage(request: ApprovalRequest):
    """
    Approve or reject a pipeline stage.
    
    Used for human-in-the-loop approval at intent and outline stages.
    """
    logger.info(
        "stage_approval",
        session_id=request.session_id,
        approved=request.approved,
    )

    # Get blog from database to determine current stage
    # TODO: Actually query the blog and resume pipeline
    
    if request.approved:
        return BlogGenerationResponse(
            session_id=request.session_id,
            status="approved",
            stage="continuing",
            message="Stage approved. Continuing generation.",
            data={
                "approved": True,
                "next_steps": [
                    "Research phase will begin",
                    "Content will be written",
                    "Editor will review the draft"
                ],
                "estimated_time": "2-3 minutes",
                "approval_timestamp": datetime.utcnow().isoformat()
            }
        )
    else:
        return BlogGenerationResponse(
            session_id=request.session_id,
            status="rejected",
            stage="awaiting_changes",
            message=request.feedback or "Stage rejected. Please provide changes.",
            data={
                "approved": False,
                "feedback": request.feedback,
                "rejection_timestamp": datetime.utcnow().isoformat(),
                "action_required": "Please modify your request or provide additional guidance"
            }
        )


@router.get("/blog/status/{session_id}")
async def get_blog_status(session_id: str):
    """Get current status of a blog generation session."""
    # TODO: Query database for actual blog status
    return {
        "session_id": session_id,
        "status": "in_progress",
        "current_stage": "research",
        "message": "Blog is being researched and drafted",
        "progress_percentage": 45,
        "stages_completed": ["intent_clarification", "outline_generation"],
        "stages_pending": ["research", "writing", "editing", "final_review"]
    }
