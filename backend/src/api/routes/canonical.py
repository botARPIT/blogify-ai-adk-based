"""Canonical blog generation and HITL review routes.

Covers both:
  - Standalone adapter routes (/api/v1/blogs/*)
  - Aliased from internal service adapter (/internal/ai/blogs/*)

Budget enforcement (Phase 3) and HITL review (Phase 5) integrated here.
"""

from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Header, HTTPException, Request, status
from pydantic import BaseModel, Field

from src.api.auth import ensure_csrf_header, require_authenticated_user
from src.core.task_queue import QueueFullError, enqueue_blog_generation
from src.core.session_store import redis_session_service
from src.models.orm_models import BlogSessionStatus, EndUser
from src.models.repository import db_repository
from src.models.repositories.auth_user_repository import AuthUserRepository
from src.models.repositories.agent_run_repository import AgentRunRepository
from src.models.repositories.blog_session_repository import BlogSessionRepository
from src.models.repositories.blog_version_repository import BlogVersionRepository
from src.models.repositories.budget_repository import BudgetRepository
from src.models.repositories.human_review_repository import HumanReviewRepository
from src.models.repositories.identity_repository import IdentityRepository
from src.models.repositories.notification_repository import NotificationRepository
from src.models.schemas import BudgetDecision, ResolvedIdentity
from src.models.schemas import (
    AgentRunSummary,
    BlogContentView,
    BlogSessionState,
    BlogVersionView,
    BudgetSnapshot,
    HumanReviewDecision,
    HumanReviewEventView,
    HumanReviewRequest,
    OutlineReviewDecision,
    OutlineReviewRequest,
    OutlineReviewView,
    OutlineSchema,
    SessionDetailView,
)
from src.services.adapter_auth_service import AdapterAuthError, AdapterAuthService
from src.services.budget_service import BudgetService
from src.services.local_auth_service import LocalAuthUser
from src.services.notification_service import NotificationService
from src.services.outline_review_service import OutlineReviewService
from src.services.revision_service import RevisionService

canonical_router = APIRouter(prefix="/api/v1", tags=["Blog Generation"])
internal_router = APIRouter(prefix="/internal/ai", tags=["Internal Service"])
APP_NAME = "blogify"
REQUEST_CONFIRMATION_FUNCTION_CALL_NAME = "adk_request_confirmation"


# ---------------------------------------------------------------------------
# Request / Response models for the canonical routes
# ---------------------------------------------------------------------------


class GenerateBlogRequest(BaseModel):
    """Request body for blog generation (standalone mode)."""

    topic: str = Field(min_length=10, max_length=500, description="Blog topic")
    audience: Optional[str] = Field(default=None, max_length=255)
    tone: Optional[str] = Field(default=None, max_length=100)
    user_id: Optional[str] = Field(default=None, description="Deprecated; resolved from auth cookie")


class ServiceGenerateBlogRequest(BaseModel):
    """Request body for Blogify server-to-server blog generation."""

    topic: str = Field(min_length=10, max_length=500)
    audience: Optional[str] = Field(default=None)
    tone: Optional[str] = Field(default=None)

    # Identity fields required for service mode
    tenant_id: str = Field(description="Blogify workspace/org ID")
    end_user_id: str = Field(description="ID of the end user requesting the blog")
    request_id: str = Field(description="Idempotency key for this request")
    external_blog_id: Optional[str] = Field(default=None, description="Blogify blog record ID")
    callback_url: Optional[str] = Field(default=None, description="Webhook callback URL")


class GenerateBlogResponse(BaseModel):
    """Response after accepting a blog generation request."""

    session_id: str
    status: str
    message: str
    budget_reserved_usd: float = 0.0


class SessionStatusResponse(BaseModel):
    """Polling endpoint response — current session state."""

    session_id: str
    status: str
    current_stage: Optional[str]
    iteration_count: int
    topic: str
    requires_human_review: bool
    budget_spent_usd: float
    budget_spent_tokens: int
    current_version_number: Optional[int]


def _build_blog_version_view(version, session_id: int) -> BlogVersionView:
    return BlogVersionView(
        version_id=version.id,
        session_id=session_id,
        version_number=version.version_number,
        source_type=version.source_type,
        title=version.title,
        content_markdown=version.content_markdown,
        word_count=version.word_count,
        sources_count=version.sources_count,
        editor_status=version.editor_status,
        created_by=version.created_by,
        created_at=version.created_at,
    )


def _build_session_state(session, latest_version) -> BlogSessionState:
    return BlogSessionState(
        session_id=session.id,
        status=session.status,
        current_stage=session.current_stage,
        iteration_count=session.iteration_count,
        topic=session.topic,
        audience=session.audience,
        requires_human_review=session.status in {
            BlogSessionStatus.AWAITING_OUTLINE_REVIEW.value,
            BlogSessionStatus.AWAITING_HUMAN_REVIEW.value,
        },
        budget_spent_usd=session.budget_spent_usd,
        budget_spent_tokens=session.budget_spent_tokens,
        remaining_revision_iterations=0,
        current_version_number=latest_version.version_number if latest_version else None,
        created_at=session.created_at,
        updated_at=session.updated_at,
        completed_at=session.completed_at,
    )


def _build_outline_review_view(session) -> OutlineReviewView | None:
    if not session.outline_data:
        return None
    return OutlineReviewView(
        session_id=session.id,
        status=session.status,
        current_stage=session.current_stage,
        topic=session.topic,
        audience=session.audience,
        feedback_text=session.outline_feedback,
        outline=OutlineSchema.model_validate(session.outline_data),
    )


def _build_agent_run_summary(run) -> AgentRunSummary:
    return AgentRunSummary(
        run_id=run.id,
        stage_name=run.stage_name,
        agent_name=run.agent_name,
        status=run.status,
        prompt_tokens=run.prompt_tokens,
        completion_tokens=run.completion_tokens,
        cost_usd=run.cost_usd,
        latency_ms=run.latency_ms,
        started_at=run.started_at,
        completed_at=run.completed_at,
        error_message=run.error_message,
    )


def _build_review_event_view(event) -> HumanReviewEventView:
    return HumanReviewEventView(
        event_id=event.id,
        session_id=event.blog_session_id,
        version_id=event.blog_version_id,
        reviewer_user_id=event.reviewer_user_id,
        action=event.action,
        feedback_text=event.feedback_text,
        review_context=event.review_context,
        created_at=event.created_at,
    )


async def _assert_owned_session(blog_session, external_user_id: str, session) -> None:
    end_user = await session.get(EndUser, blog_session.end_user_id)
    if end_user is None or end_user.external_user_id != external_user_id:
        raise HTTPException(status_code=403, detail="You do not have access to this session")


async def _resolve_authenticated_identity(request: Request) -> tuple[LocalAuthUser, ResolvedIdentity]:
    user = require_authenticated_user(request)
    identity = await _resolve_standalone_identity(user.user_id, email=user.email)
    return (
        LocalAuthUser(
            user_id=int(user.user_id),
            email=user.email or "",
            display_name=user.display_name,
        ),
        identity,
    )


async def _resolve_standalone_identity(user_id: str, email: str | None = None) -> ResolvedIdentity:
    async with db_repository.async_session() as session:
        async with session.begin():
            identity_repo = IdentityRepository(session)
            auth_service = AdapterAuthService(identity_repo)
            return await auth_service.resolve_standalone_mode(
                external_user_id=user_id,
                email=email,
            )


async def _resolve_service_identity(
    raw_api_key: str,
    external_user_id: str,
    external_tenant_id: Optional[str],
) -> ResolvedIdentity:
    async with db_repository.async_session() as session:
        async with session.begin():
            identity_repo = IdentityRepository(session)
            auth_service = AdapterAuthService(identity_repo)
            return await auth_service.resolve_service_mode(
                raw_api_key=raw_api_key,
                external_tenant_id=external_tenant_id,
                external_user_id=external_user_id,
            )


async def _resolve_standalone_budget(user_id: str) -> tuple[int, int]:
    identity = await _resolve_standalone_identity(user_id)
    return identity.tenant_id, identity.end_user_id


async def _resolve_service_budget(
    raw_api_key: str,
    external_user_id: str,
    external_tenant_id: Optional[str],
) -> tuple[int, int]:
    identity = await _resolve_service_identity(
        raw_api_key=raw_api_key,
        external_user_id=external_user_id,
        external_tenant_id=external_tenant_id,
    )
    return identity.tenant_id, identity.end_user_id


async def _get_session_status(session_id: int, external_user_id: str | None = None) -> SessionStatusResponse:
    async with db_repository.async_session() as session:
        session_repo = BlogSessionRepository(session)
        version_repo = BlogVersionRepository(session)

        blog_session = await session_repo.get_by_id(session_id)
        if blog_session is None:
            raise HTTPException(status_code=404, detail="Blog session not found")
        if external_user_id is not None:
            await _assert_owned_session(blog_session, external_user_id, session)

        latest_version = await version_repo.get_latest_for_session(session_id)

        return SessionStatusResponse(
            session_id=str(blog_session.id),
            status=blog_session.status,
            current_stage=blog_session.current_stage,
            iteration_count=blog_session.iteration_count,
            topic=blog_session.topic,
            requires_human_review=blog_session.status in {
                BlogSessionStatus.AWAITING_OUTLINE_REVIEW.value,
                BlogSessionStatus.AWAITING_HUMAN_REVIEW.value,
            },
            budget_spent_usd=blog_session.budget_spent_usd,
            budget_spent_tokens=blog_session.budget_spent_tokens,
            current_version_number=latest_version.version_number if latest_version else None,
        )


async def _get_outline_review(session_id: int, external_user_id: str | None = None) -> OutlineReviewView:
    async with db_repository.async_session() as session:
        session_repo = BlogSessionRepository(session)
        blog_session = await session_repo.get_by_id(session_id)
        if blog_session is None:
            raise HTTPException(status_code=404, detail="Blog session not found")
        if external_user_id is not None:
            await _assert_owned_session(blog_session, external_user_id, session)
        if not blog_session.outline_data:
            raise HTTPException(status_code=404, detail="Outline not generated yet")

        return _build_outline_review_view(blog_session)  # type: ignore[return-value]


async def _get_latest_version(session_id: int, external_user_id: str | None = None) -> BlogVersionView:
    async with db_repository.async_session() as session:
        session_repo = BlogSessionRepository(session)
        version_repo = BlogVersionRepository(session)
        blog_session = await session_repo.get_by_id(session_id)
        if blog_session is None:
            raise HTTPException(status_code=404, detail="Blog session not found")
        if external_user_id is not None:
            await _assert_owned_session(blog_session, external_user_id, session)
        latest_version = await version_repo.get_latest_for_session(session_id)
        if latest_version is None:
            raise HTTPException(status_code=404, detail="No blog version found")
        return _build_blog_version_view(latest_version, session_id)


async def _get_content_view(session_id: int, external_user_id: str | None = None) -> BlogContentView:
    async with db_repository.async_session() as session:
        session_repo = BlogSessionRepository(session)
        version_repo = BlogVersionRepository(session)

        blog_session = await session_repo.get_by_id(session_id)
        if blog_session is None:
            raise HTTPException(status_code=404, detail="Blog session not found")
        if external_user_id is not None:
            await _assert_owned_session(blog_session, external_user_id, session)

        latest_version = await version_repo.get_latest_for_session(session_id)
        if latest_version is None or not latest_version.content_markdown:
            raise HTTPException(
                status_code=404,
                detail="Final blog content is not available for this session",
            )

        return BlogContentView(
            session_id=blog_session.id,
            version_id=latest_version.id,
            title=latest_version.title,
            content_markdown=latest_version.content_markdown,
            word_count=latest_version.word_count,
            sources_count=latest_version.sources_count,
            topic=blog_session.topic,
            audience=blog_session.audience,
            status=blog_session.status,
        )


async def _get_session_detail(session_id: int, external_user_id: str | None = None) -> SessionDetailView:
    async with db_repository.async_session() as session:
        session_repo = BlogSessionRepository(session)
        version_repo = BlogVersionRepository(session)
        review_repo = HumanReviewRepository(session)
        run_repo = AgentRunRepository(session)

        blog_session = await session_repo.get_by_id(session_id)
        if blog_session is None:
            raise HTTPException(status_code=404, detail="Blog session not found")
        if external_user_id is not None:
            await _assert_owned_session(blog_session, external_user_id, session)

        latest_version = await version_repo.get_latest_for_session(session_id)
        review_events = await review_repo.get_for_session(session_id)
        agent_runs = await run_repo.get_for_session(session_id)

        return SessionDetailView(
            session=_build_session_state(blog_session, latest_version),
            outline=_build_outline_review_view(blog_session),
            latest_version=(
                _build_blog_version_view(latest_version, session_id)
                if latest_version is not None
                else None
            ),
            review_events=[_build_review_event_view(event) for event in review_events],
            agent_runs=[_build_agent_run_summary(run) for run in agent_runs],
        )


async def _submit_outline_review(
    *,
    session_id: int,
    request: OutlineReviewRequest,
    external_user_id: str | None = None,
) -> OutlineReviewDecision:
    async with db_repository.async_session() as session:
        async with session.begin():
            session_repo = BlogSessionRepository(session)
            existing_session = await session_repo.get_by_id(session_id)
            if existing_session is None:
                raise HTTPException(status_code=404, detail="Blog session not found")
            if external_user_id is not None:
                await _assert_owned_session(existing_session, external_user_id, session)
            review_service = OutlineReviewService(
                session_repo=session_repo,
            )
            decision = await review_service.process_review(
                blog_session_id=session_id,
                request=request,
            )
            blog_session = await session_repo.get_by_id(session_id)
            end_user = None
            if blog_session is not None:
                end_user = await session.get(EndUser, blog_session.end_user_id)

    if request.action == "approve" and blog_session is not None:
        if end_user is None:
            raise HTTPException(status_code=500, detail="Unable to resolve the current user session.")
        try:
            invocation_id, confirmation_request_id = await _get_pending_outline_confirmation(
                session_id=blog_session.id,
                external_user_id=end_user.external_user_id,
            )
            await enqueue_blog_generation(
                user_id=end_user.external_user_id,
                topic=blog_session.topic,
                audience=blog_session.audience,
                session_id=str(blog_session.id),
                blog_id=None,
                canonical_session_id=blog_session.id,
                tenant_id=blog_session.tenant_id,
                end_user_id=blog_session.end_user_id,
                job_phase="resume_after_outline",
                invocation_id=invocation_id,
                confirmation_request_id=confirmation_request_id,
                approved_outline=decision.outline.model_dump(),
                outline_feedback=request.feedback_text,
            )
        except QueueFullError as exc:
            async with db_repository.async_session() as session:
                async with session.begin():
                    session_repo = BlogSessionRepository(session)
                    await session_repo.update_status(
                        session_id,
                        status=BlogSessionStatus.AWAITING_OUTLINE_REVIEW,
                        current_stage="outline_review",
                    )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(exc),
            ) from exc

    return decision


async def _get_pending_outline_confirmation(
    *,
    session_id: int,
    external_user_id: str,
) -> tuple[str, str]:
    adk_session = await redis_session_service.get_session(
        app_name=APP_NAME,
        user_id=external_user_id,
        session_id=str(session_id),
    )
    if adk_session is None:
        raise HTTPException(status_code=404, detail="No active outline review session was found.")

    for event in reversed(adk_session.events):
        for function_call in event.get_function_calls():
            if function_call.name != REQUEST_CONFIRMATION_FUNCTION_CALL_NAME:
                continue
            args = function_call.args or {}
            original_function_call = args.get("originalFunctionCall") or {}
            if original_function_call.get("name") != "review_generated_outline":
                continue
            return event.invocation_id, function_call.id

    raise HTTPException(
        status_code=409,
        detail="No pending outline approval was found for this session.",
    )


async def _create_canonical_generation(
    *,
    identity: ResolvedIdentity,
    topic: str,
    audience: Optional[str],
    tone: Optional[str],
    external_request_id: Optional[str] = None,
    external_blog_id: Optional[str] = None,
) -> tuple[GenerateBlogResponse, str]:
    decision: BudgetDecision
    canonical_session_id: int

    async with db_repository.async_session() as session:
        async with session.begin():
            session_repo = BlogSessionRepository(session)
            budget_service = BudgetService(
                budget_repo=BudgetRepository(session),
                session_repo=session_repo,
            )

            if external_request_id:
                existing = await session_repo.get_by_external_request_id(external_request_id)
                if existing is not None:
                    return (
                        GenerateBlogResponse(
                            session_id=str(existing.id),
                            status=existing.status,
                            message="Existing session returned for request_id.",
                            budget_reserved_usd=existing.budget_reserved_usd,
                        ),
                        str(existing.id),
                    )

            decision = await budget_service.preflight(
                tenant_id=identity.tenant_id,
                end_user_id=identity.end_user_id,
            )
            if not decision.allowed:
                raise HTTPException(
                    status_code=status.HTTP_402_PAYMENT_REQUIRED,
                    detail=decision.reason or "Budget exhausted",
                )

            canonical_session = await session_repo.create(
                tenant_id=identity.tenant_id,
                end_user_id=identity.end_user_id,
                service_client_id=identity.service_client_id,
                topic=topic,
                audience=audience,
                tone=tone,
                external_request_id=external_request_id,
                external_blog_id=external_blog_id,
                budget_reserved_usd=decision.reserved_usd,
                budget_reserved_tokens=decision.reserved_tokens,
            )
            await budget_service.reserve(
                tenant_id=identity.tenant_id,
                end_user_id=identity.end_user_id,
                blog_session_id=canonical_session.id,
                decision=decision,
            )
            canonical_session_id = int(canonical_session.id)

    try:
        task_id = await enqueue_blog_generation(
            user_id=identity.external_user_id,
            topic=topic,
            audience=audience,
            session_id=str(canonical_session_id),
            blog_id=None,
            canonical_session_id=canonical_session_id,
            tenant_id=identity.tenant_id,
            end_user_id=identity.end_user_id,
            job_phase="outline_gate",
        )
    except QueueFullError as exc:
        async with db_repository.async_session() as session:
            async with session.begin():
                session_repo = BlogSessionRepository(session)
                budget_service = BudgetService(
                    budget_repo=BudgetRepository(session),
                    session_repo=session_repo,
                )
                await session_repo.update_status(
                    canonical_session_id,
                    status=BlogSessionStatus.FAILED,
                    current_stage="queue_rejected",
                )
                await budget_service.release(
                    tenant_id=identity.tenant_id,
                    end_user_id=identity.end_user_id,
                    blog_session_id=canonical_session_id,
                    reserved_usd=decision.reserved_usd,
                    reserved_tokens=decision.reserved_tokens,
                )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except Exception:
        async with db_repository.async_session() as session:
            async with session.begin():
                session_repo = BlogSessionRepository(session)
                budget_service = BudgetService(
                    budget_repo=BudgetRepository(session),
                    session_repo=session_repo,
                )
                await session_repo.update_status(
                    canonical_session_id,
                    status=BlogSessionStatus.FAILED,
                    current_stage="queue_failed",
                )
                await budget_service.release(
                    tenant_id=identity.tenant_id,
                    end_user_id=identity.end_user_id,
                    blog_session_id=canonical_session_id,
                    reserved_usd=decision.reserved_usd,
                    reserved_tokens=decision.reserved_tokens,
                )
        raise

    return (
        GenerateBlogResponse(
            session_id=str(canonical_session_id),
            status="queued",
            message="Blog generation queued.",
            budget_reserved_usd=decision.reserved_usd,
        ),
        task_id,
    )


# ---------------------------------------------------------------------------
# Standalone routes
# ---------------------------------------------------------------------------


@canonical_router.post("/blogs/generate", response_model=GenerateBlogResponse)
async def generate_blog(request: GenerateBlogRequest, http_request: Request):
    """Accept a new blog generation request (standalone mode).

    Resolves standalone identity, reserves budget, creates a canonical session,
    and reuses the existing worker queue for execution.
    """
    ensure_csrf_header(http_request)
    _, identity = await _resolve_authenticated_identity(http_request)
    response, _ = await _create_canonical_generation(
        identity=identity,
        topic=request.topic,
        audience=request.audience,
        tone=request.tone,
    )
    return response


@canonical_router.get("/blogs/{session_id}", response_model=SessionStatusResponse)
async def get_blog_session(session_id: str, request: Request):
    """Poll session status."""
    try:
        return await _get_session_status(int(session_id), require_authenticated_user(request).user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="session_id must be an integer")


@canonical_router.get("/blogs/{session_id}/outline", response_model=OutlineReviewView)
async def get_blog_outline(session_id: str, request: Request):
    """Fetch the generated outline for human review."""
    try:
        return await _get_outline_review(int(session_id), require_authenticated_user(request).user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="session_id must be an integer")


@canonical_router.get("/blogs/{session_id}/versions/latest", response_model=BlogVersionView)
async def get_latest_blog_version(session_id: str, request: Request):
    """Return the latest materialized blog version for the session."""
    try:
        return await _get_latest_version(int(session_id), require_authenticated_user(request).user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="session_id must be an integer")


@canonical_router.get("/blogs/{session_id}/content", response_model=BlogContentView)
async def get_blog_content(session_id: str, request: Request):
    """Return the latest readable content for the session."""
    try:
        return await _get_content_view(int(session_id), require_authenticated_user(request).user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="session_id must be an integer")


@canonical_router.get("/blogs/{session_id}/detail", response_model=SessionDetailView)
async def get_blog_detail(session_id: str, request: Request):
    """Return the full canonical session detail for debugging and UI inspection."""
    try:
        return await _get_session_detail(int(session_id), require_authenticated_user(request).user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="session_id must be an integer")


@canonical_router.post(
    "/blogs/{session_id}/outline/review",
    response_model=OutlineReviewDecision,
)
async def submit_outline_review(
    session_id: str,
    request: OutlineReviewRequest,
    http_request: Request,
):
    """Save outline edits or approve the outline and resume drafting."""
    try:
        ensure_csrf_header(http_request)
        current_user = require_authenticated_user(http_request)
        normalized = request.model_copy(
            update={"reviewer_user_id": current_user.email or current_user.user_id}
        )
        return await _submit_outline_review(
            session_id=int(session_id),
            request=normalized,
            external_user_id=current_user.user_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@canonical_router.post(
    "/blogs/{session_id}/review",
    response_model=HumanReviewDecision,
    summary="Submit human review decision (approve / request_revision / reject)",
)
async def submit_human_review(
    session_id: str,
    version_id: int,
    request: HumanReviewRequest,
    http_request: Request,
):
    """Phase 5: HITL review endpoint.

    After the editor stage completes, the session enters 'awaiting_human_review'.
    The reviewer calls this endpoint to approve, request revision, or reject the blog.

    Args:
        session_id: The blog session ID.
        version_id: The specific version being reviewed (latest version from polling).
        request: Review action and optional feedback.

    Returns:
        HumanReviewDecision: New session state after the review action.
    """
    try:
        blog_session_id = int(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="session_id must be an integer")

    ensure_csrf_header(http_request)
    current_user = require_authenticated_user(http_request)

    async with db_repository.async_session() as session:
        async with session.begin():
            session_repo = BlogSessionRepository(session)
            existing_session = await session_repo.get_by_id(blog_session_id)
            if existing_session is None:
                raise HTTPException(status_code=404, detail="Blog session not found")
            await _assert_owned_session(existing_session, current_user.user_id, session)
            revision_service = RevisionService(
                session_repo=session_repo,
                version_repo=BlogVersionRepository(session),
                review_repo=HumanReviewRepository(session),
                budget_repo=BudgetRepository(session),
                auth_user_repo=AuthUserRepository(session),
                notification_repo=NotificationRepository(session),
            )
            return await revision_service.process_review(
                blog_session_id=blog_session_id,
                blog_version_id=version_id,
                request=request.model_copy(
                    update={"reviewer_user_id": current_user.email or current_user.user_id}
                ),
            )


@canonical_router.get("/budgets/me", response_model=BudgetSnapshot)
async def get_my_budget(request: Request):
    """Return current budget snapshot for the calling user (standalone mode)."""
    current_user = require_authenticated_user(request)
    tenant_id, end_user_id = await _resolve_standalone_budget(current_user.user_id)
    async with db_repository.async_session() as session:
        budget_service = BudgetService(
            budget_repo=BudgetRepository(session),
            session_repo=BlogSessionRepository(session),
        )
        return await budget_service.get_snapshot(tenant_id, end_user_id)


# ---------------------------------------------------------------------------
# Internal service routes (Blogify server-to-server)
# ---------------------------------------------------------------------------


@internal_router.post("/blogs", response_model=GenerateBlogResponse)
async def service_generate_blog(
    request: ServiceGenerateBlogRequest,
    x_internal_api_key: Annotated[Optional[str], Header()] = None,
):
    """Accept blog generation request from Blogify backend (service mode).

    Requires:
        X-Internal-Api-Key: header with Blogify service API key
        tenant_id, end_user_id, request_id in body
    """
    if not x_internal_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="X-Internal-Api-Key header is required for service mode",
        )

    try:
        identity = await _resolve_service_identity(
            raw_api_key=x_internal_api_key,
            external_user_id=request.end_user_id,
            external_tenant_id=request.tenant_id,
        )
    except AdapterAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc))

    response, _ = await _create_canonical_generation(
        identity=identity,
        topic=request.topic,
        audience=request.audience,
        tone=request.tone,
        external_request_id=request.request_id,
        external_blog_id=request.external_blog_id,
    )
    return response


@internal_router.get("/blogs/{session_id}", response_model=SessionStatusResponse)
async def service_get_session(
    session_id: str,
    x_internal_api_key: Annotated[Optional[str], Header()] = None,
):
    """Get session status (service mode)."""
    if not x_internal_api_key:
        raise HTTPException(status_code=401, detail="X-Internal-Api-Key required")
    try:
        return await _get_session_status(int(session_id))
    except ValueError:
        raise HTTPException(status_code=400, detail="session_id must be an integer")


@internal_router.get("/blogs/{session_id}/outline", response_model=OutlineReviewView)
async def service_get_outline(
    session_id: str,
    x_internal_api_key: Annotated[Optional[str], Header()] = None,
):
    if not x_internal_api_key:
        raise HTTPException(status_code=401, detail="X-Internal-Api-Key required")
    try:
        return await _get_outline_review(int(session_id))
    except ValueError:
        raise HTTPException(status_code=400, detail="session_id must be an integer")


@internal_router.get("/blogs/{session_id}/versions/latest", response_model=BlogVersionView)
async def service_get_latest_version(
    session_id: str,
    x_internal_api_key: Annotated[Optional[str], Header()] = None,
):
    if not x_internal_api_key:
        raise HTTPException(status_code=401, detail="X-Internal-Api-Key required")
    try:
        return await _get_latest_version(int(session_id))
    except ValueError:
        raise HTTPException(status_code=400, detail="session_id must be an integer")


@internal_router.get("/blogs/{session_id}/content", response_model=BlogContentView)
async def service_get_content(
    session_id: str,
    x_internal_api_key: Annotated[Optional[str], Header()] = None,
):
    if not x_internal_api_key:
        raise HTTPException(status_code=401, detail="X-Internal-Api-Key required")
    try:
        return await _get_content_view(int(session_id))
    except ValueError:
        raise HTTPException(status_code=400, detail="session_id must be an integer")


@internal_router.get("/blogs/{session_id}/detail", response_model=SessionDetailView)
async def service_get_detail(
    session_id: str,
    x_internal_api_key: Annotated[Optional[str], Header()] = None,
):
    if not x_internal_api_key:
        raise HTTPException(status_code=401, detail="X-Internal-Api-Key required")
    try:
        return await _get_session_detail(int(session_id))
    except ValueError:
        raise HTTPException(status_code=400, detail="session_id must be an integer")


@internal_router.post(
    "/blogs/{session_id}/outline/review",
    response_model=OutlineReviewDecision,
)
async def service_submit_outline_review(
    session_id: str,
    request: OutlineReviewRequest,
    x_internal_api_key: Annotated[Optional[str], Header()] = None,
):
    if not x_internal_api_key:
        raise HTTPException(status_code=401, detail="X-Internal-Api-Key required")
    try:
        return await _submit_outline_review(session_id=int(session_id), request=request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@internal_router.post("/blogs/{session_id}/review", response_model=HumanReviewDecision)
async def service_submit_review(
    session_id: str,
    version_id: int,
    request: HumanReviewRequest,
    x_internal_api_key: Annotated[Optional[str], Header()] = None,
):
    """Submit review (service mode). Mirrors standalone /review endpoint."""
    if not x_internal_api_key:
        raise HTTPException(status_code=401, detail="X-Internal-Api-Key required")

    try:
        blog_session_id = int(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="session_id must be an integer")

    async with db_repository.async_session() as session:
        async with session.begin():
            revision_service = RevisionService(
                session_repo=BlogSessionRepository(session),
                version_repo=BlogVersionRepository(session),
                review_repo=HumanReviewRepository(session),
                budget_repo=BudgetRepository(session),
            )
            return await revision_service.process_review(
                blog_session_id=blog_session_id,
                blog_version_id=version_id,
                request=request,
            )


@internal_router.get("/budgets/{end_user_id}", response_model=BudgetSnapshot)
async def service_get_budget(
    end_user_id: str,
    tenant_id: Optional[str] = None,
    x_internal_api_key: Annotated[Optional[str], Header()] = None,
):
    """Return budget snapshot for a specific end user (service mode)."""
    if not x_internal_api_key:
        raise HTTPException(status_code=401, detail="X-Internal-Api-Key required")

    try:
        resolved_tenant_id, resolved_end_user_id = await _resolve_service_budget(
            raw_api_key=x_internal_api_key,
            external_user_id=end_user_id,
            external_tenant_id=tenant_id,
        )
    except AdapterAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc))

    async with db_repository.async_session() as session:
        budget_service = BudgetService(
            budget_repo=BudgetRepository(session),
            session_repo=BlogSessionRepository(session),
        )
        return await budget_service.get_snapshot(
            resolved_tenant_id,
            resolved_end_user_id,
        )
