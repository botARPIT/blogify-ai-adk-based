"""Blog generation API routes with production features.

Includes:
- Idempotency support
- Async task queue integration
- Input sanitization
"""

from fastapi import APIRouter, HTTPException, Header, Request
from pydantic import BaseModel, Field

from src.config.logging_config import get_logger
from src.controllers.blog_controller import blog_controller
from src.core.idempotency import idempotency_store

logger = get_logger(__name__)

router = APIRouter()


class BlogGenerationRequest(BaseModel):
    """Blog generation request model."""

    user_id: str = Field(..., description="User identifier")
    topic: str = Field(..., min_length=10, max_length=500, description="Blog topic")
    audience: str | None = Field(None, max_length=200, description="Target audience")
    sync: bool = Field(False, description="If true, generate synchronously without approvals")
    async_mode: bool = Field(False, description="If true, return task_id immediately for polling")


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
    task_id: str | None = None  # For async mode


class TaskStatusResponse(BaseModel):
    """Async task status response."""
    
    task_id: str
    status: str
    progress: int | None = None
    result: dict | None = None
    error: str | None = None


@router.post("/blog/generate", response_model=BlogGenerationResponse)
async def generate_blog(
    request: BlogGenerationRequest,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
):
    """
    Initiate blog generation.
    
    **Modes:**
    - `sync=False` (default): HITL workflow, pauses for approval at each stage
    - `sync=True`: Full generation without pauses
    - `async_mode=True`: Returns task_id immediately, poll /blog/task/{id} for status
    
    **Idempotency:**
    Provide `Idempotency-Key` header to prevent duplicate processing on retries.
    Same key within 24 hours returns cached response.
    """
    try:
        # Check idempotency
        is_new, cached_response = await idempotency_store.check_and_set(
            user_id=request.user_id,
            endpoint="/blog/generate",
            idempotency_key=idempotency_key,
            request_body=request.model_dump(),
        )
        
        if not is_new:
            if cached_response:
                logger.info("idempotency_cache_hit", user_id=request.user_id)
                return BlogGenerationResponse(**cached_response)
            else:
                # Request in progress
                raise HTTPException(
                    status_code=409,
                    detail="Request already in progress with this idempotency key",
                )
        
        # Async mode - return immediately with task_id
        if request.async_mode:
            from src.core.task_queue import enqueue_blog_generation
            
            task_id = await enqueue_blog_generation(
                user_id=request.user_id,
                topic=request.topic,
                audience=request.audience,
            )
            
            response = BlogGenerationResponse(
                session_id="",
                status="queued",
                stage="pending",
                message="Blog generation queued. Poll /blog/task/{task_id} for status.",
                task_id=task_id,
            )
            
            # Cache the response
            await idempotency_store.set_response(
                user_id=request.user_id,
                endpoint="/blog/generate",
                response=response.model_dump(),
                idempotency_key=idempotency_key,
                request_body=request.model_dump(),
            )
            
            return response
        
        # Synchronous mode
        if request.sync:
            result = await blog_controller.generate_blog_sync(
                user_id=request.user_id,
                topic=request.topic,
                audience=request.audience
            )
            response = BlogGenerationResponse(**result)
        else:
            # HITL mode
            result = await blog_controller.initiate_blog_generation(
                user_id=request.user_id,
                topic=request.topic,
                audience=request.audience
            )
            response = BlogGenerationResponse(**result)
        
        # Cache successful response
        await idempotency_store.set_response(
            user_id=request.user_id,
            endpoint="/blog/generate",
            response=response.model_dump(),
            idempotency_key=idempotency_key,
            request_body=request.model_dump(),
        )
        
        return response
    
    except HTTPException:
        raise
    except RuntimeError as e:
        # Rate limit or circuit breaker
        await idempotency_store.clear(
            user_id=request.user_id,
            endpoint="/blog/generate",
            idempotency_key=idempotency_key,
            request_body=request.model_dump(),
        )
        raise HTTPException(status_code=429, detail=str(e))
    except ValueError as e:
        await idempotency_store.clear(
            user_id=request.user_id,
            endpoint="/blog/generate",
            idempotency_key=idempotency_key,
            request_body=request.model_dump(),
        )
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("blog_generation_failed", error=str(e))
        await idempotency_store.clear(
            user_id=request.user_id,
            endpoint="/blog/generate",
            idempotency_key=idempotency_key,
            request_body=request.model_dump(),
        )
        raise HTTPException(status_code=500, detail=f"Blog generation failed: {str(e)}")


@router.get("/blog/task/{task_id}", response_model=TaskStatusResponse)
async def get_task_status(task_id: str):
    """
    Get async blog generation task status.
    
    Poll this endpoint for progress updates when using `async_mode=True`.
    
    **Status values:**
    - `pending`: Waiting in queue
    - `processing`: Generation in progress
    - `completed`: Done - result available
    - `failed`: Error occurred
    """
    try:
        from src.core.task_queue import get_generation_status
        
        status = await get_generation_status(task_id)
        
        if status is None:
            raise HTTPException(status_code=404, detail="Task not found")
        
        return TaskStatusResponse(
            task_id=task_id,
            status=status.get("status", "unknown"),
            progress=status.get("progress"),
            result=status.get("result"),
            error=status.get("error"),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("task_status_failed", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to get task status")


@router.post("/blog/approve", response_model=BlogGenerationResponse)
async def approve_stage(request: ApprovalRequest):
    """
    Approve or reject a pipeline stage.
    
    Approval continues to next stage in pipeline.
    Rejection returns feedback for modifications.
    """
    try:
        result = await blog_controller.handle_stage_approval(
            session_id=request.session_id,
            approved=request.approved,
            feedback=request.feedback
        )
        return BlogGenerationResponse(**result)
    
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("approval_failed", error=str(e))
        raise HTTPException(status_code=500, detail=f"Approval processing failed: {str(e)}")


@router.get("/blog/status/{session_id}")
async def get_blog_status(session_id: str):
    """
    Get current status of a blog generation session.
    
    Includes current stage, stage data, and progress.
    """
    try:
        return await blog_controller.get_blog_status(session_id)
    
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("status_check_failed", error=str(e))
        raise HTTPException(status_code=500, detail="Status check failed")


@router.get("/blog/content/{session_id}")
async def get_blog_content(session_id: str):
    """
    Get the final generated blog content.
    
    Only available after blog is completed.
    """
    try:
        return await blog_controller.get_blog_content(session_id)
    
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("content_fetch_failed", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to fetch blog content")
