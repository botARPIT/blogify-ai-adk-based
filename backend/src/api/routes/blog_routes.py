"""HTTP boundary for blog workflow commands and query projections."""

import shutil
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from src.api.auth import AuthenticatedUser, get_current_user, require_authenticated_user
from src.api.dependencies import get_blog_read_service, get_blog_service
from src.guards.input_guard import InputGuard
from src.models.orm_models import BlogSessionStatus
from src.models.schemas import (
    BlogContentView,
    BlogInsightsResponse,
    BlogSessionDetail,
    BlogSessionMetrics,
    BlogSessionPage,
    BlogVersionView,
    BudgetResponse,
    FinalReviewRequest,
    GenerateRequest,
    GenerateResponse,
    OutlineFrontendDecision,
    OutlineFrontendRequest,
    OutlineReviewRequest,
    OutlineReviewView,
    SessionStatusResponse,
)
from src.services.blog_export_service import BlogExportService
from src.services.blog_read_service import BlogReadService
from src.services.blog_service import BlogService
from src.services.exceptions import (
    DailyBlogLimitExceededError,
    InsufficientBudgetError,
    SessionTerminalError,
)

router = APIRouter(prefix="/blogs", tags=["blogs"])
input_guard = InputGuard()


def _user_id(user: AuthenticatedUser | None) -> int:
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return int(user.user_id)


def _not_found_or_conflict(error: ValueError) -> HTTPException:
    message = str(error)
    return HTTPException(
        status_code=404
        if message
        in {
            "Session not found",
            "No outline available",
            "No blog version found",
            "Final blog content is not available for this session",
        }
        else 409,
        detail=message,
    )


@router.post("/generate", status_code=202, response_model=GenerateResponse)
async def generate_blog(
    body: GenerateRequest,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    user: AuthenticatedUser = Depends(require_authenticated_user),
    service: BlogService = Depends(get_blog_service),
) -> GenerateResponse:
    valid, error = input_guard.validate(body.topic, body.audience, body.tone)
    if not valid:
        raise HTTPException(status_code=400, detail=error)
    try:
        result = await service.create_generation(
            user_id=_user_id(user),
            topic=body.topic,
            audience=body.audience,
            tone=body.tone,
            idempotency_key=idempotency_key or body.idempotency_key,
        )
        await service.commit_and_dispatch(result.id)
        return GenerateResponse(
            session_id=result.id,
            status=result.status,
            adk_session_id=result.adk_session_id,
            created_at=result.created_at,
        )
    except DailyBlogLimitExceededError as exc:
        raise HTTPException(
            status_code=429,
            detail={
                "error_code": "DAILY_BLOG_LIMIT_REACHED",
                "message": str(exc),
                "daily_limit": exc.daily_limit,
                "resets_at": "00:00 UTC",
            },
        ) from exc
    except SessionTerminalError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "error_code": "SESSION_TERMINAL",
                "message": "This request ID has already completed. Generate a new Idempotency-Key to retry.",
            },
        ) from exc
    except InsufficientBudgetError as exc:
        raise HTTPException(status_code=402, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=409 if "active" in str(exc) else 400, detail=str(exc)
        ) from exc


@router.get("/", response_model=BlogSessionPage)
async def list_blogs(
    page: int = Query(1, ge=1),
    page_size: int = Query(12, ge=1, le=50),
    status: list[BlogSessionStatus] | None = Query(None),
    q: str | None = Query(None, max_length=100),
    user: AuthenticatedUser | None = Depends(get_current_user),
    service: BlogReadService = Depends(get_blog_read_service),
) -> BlogSessionPage:
    return await service.list_sessions(
        _user_id(user), page, page_size, status, q.strip() if q and q.strip() else None
    )


@router.get("/insights", response_model=BlogInsightsResponse)
async def get_blog_insights(
    days: int = Query(30, ge=7, le=365),
    user: AuthenticatedUser | None = Depends(get_current_user),
    service: BlogReadService = Depends(get_blog_read_service),
) -> BlogInsightsResponse:
    return await service.insights(_user_id(user), days)


@router.get("/budget", response_model=BudgetResponse)
async def get_budget(
    user: AuthenticatedUser | None = Depends(get_current_user),
    service: BlogReadService = Depends(get_blog_read_service),
) -> BudgetResponse:
    return await service.budget(_user_id(user))


@router.get("/{session_id}/outline", response_model=OutlineReviewView)
async def get_outline(
    session_id: int,
    user: AuthenticatedUser | None = Depends(get_current_user),
    service: BlogReadService = Depends(get_blog_read_service),
) -> OutlineReviewView:
    try:
        return await service.outline(_user_id(user), session_id)
    except ValueError as exc:
        raise _not_found_or_conflict(exc) from exc


@router.post("/{session_id}/outline/review", response_model=OutlineFrontendDecision)
async def submit_outline_review_frontend(
    session_id: int,
    body: OutlineFrontendRequest,
    user: AuthenticatedUser | None = Depends(get_current_user),
    service: BlogService = Depends(get_blog_service),
) -> OutlineFrontendDecision:
    if body.action not in {"approve", "revise"} or not body.edited_outline:
        raise HTTPException(status_code=400, detail="Invalid action")
    try:
        result = await service.submit_outline_review(
            user_id=_user_id(user),
            session_id=session_id,
            approved_outline=body.edited_outline,
            feedback_text=body.feedback_text,
            action=body.action,
        )
        await service.commit_and_dispatch(result.id)
        return OutlineFrontendDecision(
            session_id=result.id,
            action=body.action,
            new_status=result.status,
            current_stage=result.current_stage,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/{session_id}/status", response_model=SessionStatusResponse)
async def get_session_status(
    session_id: int,
    user: AuthenticatedUser | None = Depends(get_current_user),
    service: BlogReadService = Depends(get_blog_read_service),
) -> SessionStatusResponse:
    try:
        return await service.status(_user_id(user), session_id)
    except ValueError as exc:
        raise _not_found_or_conflict(exc) from exc


@router.get("/{session_id}/detail", response_model=BlogSessionMetrics)
async def get_session_detail(
    session_id: int,
    user: AuthenticatedUser | None = Depends(get_current_user),
    service: BlogReadService = Depends(get_blog_read_service),
) -> BlogSessionMetrics:
    try:
        return await service.detail(_user_id(user), session_id)
    except ValueError as exc:
        raise _not_found_or_conflict(exc) from exc


@router.get("/{session_id}", response_model=BlogSessionDetail)
async def get_blog(
    session_id: int,
    user: AuthenticatedUser | None = Depends(get_current_user),
    service: BlogReadService = Depends(get_blog_read_service),
) -> BlogSessionDetail:
    try:
        return await service.session(_user_id(user), session_id)
    except ValueError as exc:
        raise _not_found_or_conflict(exc) from exc


@router.post("/{session_id}/outline-review")
async def submit_outline_review(
    session_id: int,
    body: OutlineReviewRequest,
    user: AuthenticatedUser | None = Depends(get_current_user),
    service: BlogService = Depends(get_blog_service),
) -> dict:
    try:
        result = await service.submit_outline_review(
            user_id=_user_id(user),
            session_id=session_id,
            approved_outline=body.approved_outline,
            feedback_text=body.feedback_text,
        )
        await service.commit_and_dispatch(result.id)
        return {"session_id": result.id, "status": result.status}
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{session_id}/final-review")
async def submit_final_review(
    session_id: int,
    body: FinalReviewRequest,
    user: AuthenticatedUser | None = Depends(get_current_user),
    service: BlogService = Depends(get_blog_service),
) -> dict:
    try:
        result = await service.submit_final_review(
            user_id=_user_id(user),
            session_id=session_id,
            action=body.action,
            feedback_text=body.feedback_text,
        )
        await service.commit_and_dispatch(result.id)
        return {"session_id": result.id, "status": result.status}
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/{session_id}/content", response_model=BlogContentView)
async def get_content(
    session_id: int,
    user: AuthenticatedUser | None = Depends(get_current_user),
    service: BlogReadService = Depends(get_blog_read_service),
) -> BlogContentView:
    try:
        return await service.content(_user_id(user), session_id)
    except ValueError as exc:
        raise _not_found_or_conflict(exc) from exc


@router.get("/{session_id}/export")
async def export_completed_blog(
    session_id: int,
    format: Literal["pdf", "docx"] = Query(...),
    user: AuthenticatedUser | None = Depends(get_current_user),
    service: BlogReadService = Depends(get_blog_read_service),
) -> FileResponse:
    try:
        markdown, title = await service.export_markdown(_user_id(user), session_id)
        export = await BlogExportService().create(markdown, title, format)
    except ValueError as exc:
        raise _not_found_or_conflict(exc) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail="Could not convert this blog for export"
        ) from exc
    return FileResponse(
        export.path,
        media_type=export.media_type,
        filename=export.filename,
        background=BackgroundTask(shutil.rmtree, export.temp_dir, ignore_errors=True),
    )


@router.get("/{session_id}/versions/latest", response_model=BlogVersionView)
async def get_latest_version(
    session_id: int,
    user: AuthenticatedUser | None = Depends(get_current_user),
    service: BlogReadService = Depends(get_blog_read_service),
) -> BlogVersionView:
    try:
        return await service.latest_version(_user_id(user), session_id)
    except ValueError as exc:
        raise _not_found_or_conflict(exc) from exc
