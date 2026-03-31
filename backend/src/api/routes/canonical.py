"""Canonical blog generation and HITL review routes.

Covers both:
  - Standalone adapter routes (/api/v1/blogs/*)
  - Aliased from internal service adapter (/internal/ai/blogs/*)

Budget enforcement (Phase 3) and HITL review (Phase 5) integrated here.
"""

from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from src.api.auth import ensure_csrf_header, require_authenticated_user
from src.config.logging_config import get_logger
from src.core.errors import format_error_response
from src.core.idempotency import IdempotencyState, idempotency_store
from src.guards.rate_limit_guard import rate_limit_guard
from src.core.task_queue import QueueFullError, enqueue_blog_generation
from src.core.session_store import redis_session_service
from src.models.orm_models import BlogSessionStatus, EndUser, ServiceClient
from src.models.repository import db_repository
from src.models.repositories.auth_user_repository import AuthUserRepository
from src.models.repositories.agent_run_repository import AgentRunRepository
from src.models.repositories.blog_session_repository import BlogSessionRepository
from src.models.repositories.blog_version_repository import BlogVersionRepository
from src.models.repositories.budget_repository import BudgetRepository
from src.models.repositories.human_review_repository import HumanReviewRepository
from src.models.repositories.identity_repository import IdentityRepository
from src.models.repositories.notification_repository import NotificationRepository
from src.models.schemas import BudgetDecision, BudgetExhaustedDetail, ResolvedIdentity
from src.models.schemas import (
    AgentRunSummary,
    BlogContentView,
    BlogSessionListItem,
    BlogSessionListResponse,
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
from src.models.repositories.service_client_budget_repository import (
    ServiceClientBudgetRepository,
)
from src.services.adapter_auth_service import AdapterAuthError, AdapterAuthService
from src.services.budget_service import BudgetService
from src.services.local_auth_service import LocalAuthUser
from src.services.notification_service import NotificationService
from src.services.outline_review_service import OutlineReviewService
from src.services.revision_service import RevisionService
from src.services.service_client_budget_service import ServiceClientBudgetService
from src.monitoring.metrics import (
    blog_generations_total,
    budget_exceeded_total,
    daily_cost_usd,
    service_client_budget_exhausted_total,
    service_client_budget_preflight_total,
)

canonical_router = APIRouter(prefix="/api/v1", tags=["Blog Generation"])
internal_router = APIRouter(prefix="/internal/ai", tags=["Internal Service"])
APP_NAME = "blogify"
REQUEST_CONFIRMATION_FUNCTION_CALL_NAME = "adk_request_confirmation"
logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Budget exhaustion helper
# ---------------------------------------------------------------------------


def _raise_budget_exhausted(decision: BudgetDecision) -> None:
    """Raise a structured HTTP 402 from a denied BudgetDecision.

    Produces a JSON body that downstream service clients can deserialize:

        {
            "error": "budget_exhausted",
            "error_code": "BUDGET_EXCEEDED",          # or SERVICE_CLIENT_BUDGET_EXCEEDED
            "reason": "Daily USD budget exhausted: ...",
            "daily_remaining_usd": 0.0,
            "daily_remaining_tokens": 0,
            "daily_remaining_blog_count": 0,
            "remaining_active_session_slots": 2,
            "estimated_reset_at": "2026-04-01T00:00:00Z"
        }
    """
    from datetime import datetime, timezone

    # Next midnight UTC
    now = datetime.now(timezone.utc)
    reset_at = datetime(
        year=now.year,
        month=now.month,
        day=now.day,
        tzinfo=timezone.utc,
    ).replace(hour=0, minute=0, second=0, microsecond=0)
    # If already past midnight (i.e., today's midnight is in the past), roll to next day
    if reset_at <= now:
        from datetime import timedelta
        reset_at = reset_at + timedelta(days=1)

    body = BudgetExhaustedDetail(
        error_code=decision.error_code or "BUDGET_EXCEEDED",
        reason=decision.reason or "Budget exhausted",
        daily_remaining_usd=decision.daily_remaining_usd,
        daily_remaining_tokens=decision.daily_remaining_tokens,
        daily_remaining_blog_count=decision.daily_remaining_blog_count,
        remaining_active_session_slots=decision.remaining_active_session_slots,
        estimated_reset_at=reset_at,
    )
    raise HTTPException(
        status_code=status.HTTP_402_PAYMENT_REQUIRED,
        detail=body.model_dump(mode="json"),
    )


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


def _remaining_revision_iterations(max_iterations: int, iteration_count: int) -> int:
    return max(max_iterations - iteration_count, 0)


async def _restore_revision_denied_state(blog_session_id: int) -> None:
    """Compensate a revision request when downstream budget reservation is denied."""
    async with db_repository.async_session() as session:
        async with session.begin():
            session_repo = BlogSessionRepository(session)
            blog_session = await session_repo.get_by_id(blog_session_id)
            if blog_session is None:
                return
            blog_session.iteration_count = max(0, blog_session.iteration_count - 1)
            blog_session.status = BlogSessionStatus.AWAITING_HUMAN_REVIEW
            blog_session.current_stage = "awaiting_review"


def _build_session_state(
    session,
    latest_version,
    remaining_revision_iterations: int,
) -> BlogSessionState:
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
        remaining_revision_iterations=remaining_revision_iterations,
        current_version_number=latest_version.version_number if latest_version else None,
        created_at=session.created_at,
        updated_at=session.updated_at,
        completed_at=session.completed_at,
    )


def _build_blog_session_list_item(
    session,
    latest_version,
    remaining_revision_iterations: int,
) -> BlogSessionListItem:
    return BlogSessionListItem(
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
        remaining_revision_iterations=remaining_revision_iterations,
        current_version_number=latest_version.version_number if latest_version else None,
        latest_title=latest_version.title if latest_version else None,
        latest_word_count=latest_version.word_count if latest_version else 0,
        latest_sources_count=latest_version.sources_count if latest_version else 0,
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


async def require_internal_service_client(
    request: Request,
    raw_api_key: str | None,
    *,
    is_blog_request: bool = False,
) -> ServiceClient:
    if not raw_api_key:
        raise HTTPException(status_code=401, detail="X-Internal-Api-Key required")

    try:
        async with db_repository.async_session() as session:
            async with session.begin():
                identity_repo = IdentityRepository(session)
                auth_service = AdapterAuthService(identity_repo)
                service_client = await auth_service.validate_service_api_key(raw_api_key)
    except AdapterAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    allowed, message, rate_limit_info = await rate_limit_guard.check_service_request_limit(
        service_client.client_key
    )
    request.state.rate_limit_info = rate_limit_info
    if not allowed:
        raise HTTPException(status_code=429, detail=message)

    if is_blog_request:
        allowed, message, rate_limit_info = await rate_limit_guard.check_service_blog_generation_limit(
            service_client.client_key
        )
        request.state.rate_limit_info = rate_limit_info
        if not allowed:
            raise HTTPException(status_code=429, detail=message)

    return service_client


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


async def _get_session_identity(session_id: int) -> tuple[int, int]:
    async with db_repository.async_session() as session:
        session_repo = BlogSessionRepository(session)
        blog_session = await session_repo.get_by_id(session_id)
        if blog_session is None:
            raise HTTPException(status_code=404, detail="Blog session not found")
        return blog_session.tenant_id, blog_session.end_user_id


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
        budget_repo = BudgetRepository(session)

        blog_session = await session_repo.get_by_id(session_id)
        if blog_session is None:
            raise HTTPException(status_code=404, detail="Blog session not found")
        if external_user_id is not None:
            await _assert_owned_session(blog_session, external_user_id, session)

        latest_version = await version_repo.get_latest_for_session(session_id)
        review_events = await review_repo.get_for_session(session_id)
        agent_runs = await run_repo.get_for_session(session_id)
        policy = await budget_repo.get_effective_policy(
            blog_session.tenant_id, blog_session.end_user_id
        )
        max_iterations = policy.max_revision_iterations_per_session if policy else 0

        return SessionDetailView(
            session=_build_session_state(
                blog_session,
                latest_version,
                _remaining_revision_iterations(
                    max_iterations,
                    blog_session.iteration_count,
                ),
            ),
            outline=_build_outline_review_view(blog_session),
            latest_version=(
                _build_blog_version_view(latest_version, session_id)
                if latest_version is not None
                else None
            ),
            review_events=[_build_review_event_view(event) for event in review_events],
            agent_runs=[_build_agent_run_summary(run) for run in agent_runs],
        )


async def _list_blog_sessions(
    *,
    end_user_id: int,
    tenant_id: int,
    limit: int = 20,
    offset: int = 0,
    status_filter: str | None = None,
) -> BlogSessionListResponse:
    async with db_repository.async_session() as session:
        session_repo = BlogSessionRepository(session)
        version_repo = BlogVersionRepository(session)
        budget_repo = BudgetRepository(session)

        sessions = await session_repo.list_for_end_user(
            end_user_id=end_user_id,
            limit=limit,
            offset=offset,
            status=status_filter,
        )
        total = await session_repo.count_for_end_user(end_user_id=end_user_id, status=status_filter)
        latest_versions = await version_repo.get_latest_for_sessions([item.id for item in sessions])
        policy = await budget_repo.get_effective_policy(tenant_id, end_user_id)
        max_iterations = policy.max_revision_iterations_per_session if policy else 0

        return BlogSessionListResponse(
            items=[
                _build_blog_session_list_item(
                    item,
                    latest_versions.get(int(item.id)),
                    _remaining_revision_iterations(max_iterations, item.iteration_count),
                )
                for item in sessions
            ],
            total=total,
            limit=limit,
            offset=offset,
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


async def _submit_human_review(
    *,
    blog_session_id: int,
    version_id: int,
    request: HumanReviewRequest,
    external_user_id: str | None = None,
) -> HumanReviewDecision:
    decision: HumanReviewDecision
    blog_session = None
    end_user = None
    async with db_repository.async_session() as session:
        async with session.begin():
            session_repo = BlogSessionRepository(session)
            existing_session = await session_repo.get_by_id(blog_session_id)
            if existing_session is None:
                raise HTTPException(status_code=404, detail="Blog session not found")
            if external_user_id is not None:
                await _assert_owned_session(existing_session, external_user_id, session)
            revision_service = RevisionService(
                session_repo=session_repo,
                version_repo=BlogVersionRepository(session),
                review_repo=HumanReviewRepository(session),
                budget_repo=BudgetRepository(session),
            )
            try:
                decision = await revision_service.process_review(
                    blog_session_id=blog_session_id,
                    blog_version_id=version_id,
                    request=request,
                )
            except ValueError as exc:
                detail = str(exc)
                if "not found" in detail.lower():
                    raise HTTPException(status_code=404, detail=detail) from exc
                raise HTTPException(status_code=409, detail=detail) from exc
            blog_session = await session_repo.get_by_id(blog_session_id)
            if blog_session is not None:
                end_user = await session.get(EndUser, blog_session.end_user_id)

    if request.action == "request_revision" and blog_session is not None:
        if end_user is None:
            raise HTTPException(status_code=500, detail="Unable to resolve the current user session.")
        async with db_repository.async_session() as session:
            async with session.begin():
                session_repo = BlogSessionRepository(session)
                budget_service = BudgetService(
                    budget_repo=BudgetRepository(session),
                    session_repo=session_repo,
                )
                current_session = await session_repo.get_by_id(blog_session_id)
                if current_session is None:
                    raise HTTPException(status_code=404, detail="Blog session not found")
                reservation_context = await budget_service.reserve_revision_budget(
                    tenant_id=current_session.tenant_id,
                    end_user_id=current_session.end_user_id,
                    service_client_id=current_session.service_client_id,
                    blog_session_id=current_session.id,
                    iteration_number=current_session.iteration_count,
                    current_session_spent_usd=current_session.budget_spent_usd,
                    current_session_spent_tokens=current_session.budget_spent_tokens,
                )
                if not reservation_context.decision.allowed:
                    budget_exceeded_total.labels(
                        budget_type=reservation_context.decision.error_code or "per_user"
                    ).inc()
                    denied_reason = reservation_context.decision.reason or "Budget exhausted"
                    denied_decision = reservation_context.decision
                else:
                    current_session.budget_reserved_usd += reservation_context.decision.reserved_usd
                    current_session.budget_reserved_tokens += reservation_context.decision.reserved_tokens
                    denied_reason = None
                    denied_decision = None
        if denied_reason is not None and denied_decision is not None:
            await _restore_revision_denied_state(blog_session_id)
            _raise_budget_exhausted(denied_decision)

        try:
            await enqueue_blog_generation(
                user_id=end_user.external_user_id,
                topic=blog_session.topic,
                audience=blog_session.audience,
                session_id=str(blog_session.id),
                blog_id=None,
                canonical_session_id=blog_session.id,
                tenant_id=blog_session.tenant_id,
                end_user_id=blog_session.end_user_id,
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
                    current_session = await session_repo.get_by_id(blog_session_id)
                    await session_repo.update_status(
                        blog_session_id,
                        status=BlogSessionStatus.AWAITING_HUMAN_REVIEW,
                        current_stage="awaiting_review",
                    )
                    if current_session is not None:
                        await budget_service.release(
                            tenant_id=current_session.tenant_id,
                            end_user_id=current_session.end_user_id,
                            service_client_id=current_session.service_client_id,
                            blog_session_id=blog_session_id,
                            reason="revision_queue_rejected",
                        )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(exc),
            ) from exc

        async with db_repository.async_session() as session:
            async with session.begin():
                session_repo = BlogSessionRepository(session)
                await session_repo.update_status(
                    blog_session_id,
                    status=BlogSessionStatus.QUEUED,
                    current_stage="intent",
                )

        return HumanReviewDecision(
            session_id=decision.session_id,
            version_id=decision.version_id,
            action=decision.action,
            new_status=BlogSessionStatus.QUEUED.value,
            iteration_count=decision.iteration_count,
            requires_human_review=False,
            message="Revision requested. The session has been re-queued and will restart from intent.",
        )

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

            current_active_sessions = await session_repo.count_active_for_end_user(
                identity.end_user_id
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
            )
            reservation_context = await budget_service.reserve_generation_budget(
                tenant_id=identity.tenant_id,
                end_user_id=identity.end_user_id,
                service_client_id=identity.service_client_id,
                blog_session_id=canonical_session.id,
                current_active_sessions_override=current_active_sessions,
            )
            decision = reservation_context.decision
            if not decision.allowed:
                budget_exceeded_total.labels(
                    budget_type=decision.error_code or "per_user"
                ).inc()
                _raise_budget_exhausted(decision)

            canonical_session.budget_reserved_usd = decision.reserved_usd
            canonical_session.budget_reserved_tokens = decision.reserved_tokens
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
                    service_client_id=identity.service_client_id,
                    blog_session_id=canonical_session_id,
                    reason="queue_rejected",
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
                    service_client_id=identity.service_client_id,
                    blog_session_id=canonical_session_id,
                    reason="queue_failed",
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


async def _create_generation_response(
    *,
    identity: ResolvedIdentity,
    topic: str,
    audience: Optional[str],
    tone: Optional[str],
    external_request_id: Optional[str] = None,
    external_blog_id: Optional[str] = None,
) -> GenerateBlogResponse:
    response, _ = await _create_canonical_generation(
        identity=identity,
        topic=topic,
        audience=audience,
        tone=tone,
        external_request_id=external_request_id,
        external_blog_id=external_blog_id,
    )
    return response


async def _run_idempotent_action(
    *,
    user_scope: str,
    endpoint: str,
    idempotency_key: str | None,
    request_body: dict,
    action,
    cacheable_error_statuses: set[int],
):
    if not idempotency_key:
        return await action()

    try:
        result = await idempotency_store.check_and_set(
            user_scope=user_scope,
            endpoint=endpoint,
            idempotency_key=idempotency_key,
            request_body=request_body,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("idempotency_check_failed", endpoint=endpoint, error=str(exc))
        return await action()

    if result.state == IdempotencyState.CACHED:
        if result.status_code is not None and result.status_code >= 400:
            return JSONResponse(status_code=result.status_code, content=result.response or {})
        return result.response or {}

    if result.state == IdempotencyState.MISMATCH:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Idempotency-Key was already used with a different request payload.",
        )

    if result.state == IdempotencyState.IN_PROGRESS:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An identical request is already being processed.",
        )

    try:
        response = await action()
    except HTTPException as exc:
        should_cache = exc.status_code in cacheable_error_statuses and exc.status_code not in {401, 403}
        if should_cache:
            try:
                await idempotency_store.set_response(
                    user_scope=user_scope,
                    endpoint=endpoint,
                    idempotency_key=idempotency_key,
                    request_body=request_body,
                    status_code=exc.status_code,
                    response_body=format_error_response(exc).model_dump(),
                )
            except Exception as cache_exc:  # noqa: BLE001
                logger.warning("idempotency_cache_failed", endpoint=endpoint, error=str(cache_exc))
        else:
            try:
                await idempotency_store.clear(
                    user_scope=user_scope,
                    endpoint=endpoint,
                    idempotency_key=idempotency_key,
                )
            except Exception as clear_exc:  # noqa: BLE001
                logger.warning("idempotency_clear_failed", endpoint=endpoint, error=str(clear_exc))
        raise
    except Exception:
        try:
            await idempotency_store.clear(
                user_scope=user_scope,
                endpoint=endpoint,
                idempotency_key=idempotency_key,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("idempotency_clear_failed", endpoint=endpoint, error=str(exc))
        raise

    try:
        await idempotency_store.set_response(
            user_scope=user_scope,
            endpoint=endpoint,
            idempotency_key=idempotency_key,
            request_body=request_body,
            status_code=200,
            response_body=response.model_dump() if hasattr(response, "model_dump") else response,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("idempotency_cache_failed", endpoint=endpoint, error=str(exc))

    return response


# ---------------------------------------------------------------------------
# Standalone routes
# ---------------------------------------------------------------------------


@canonical_router.post("/blogs/generate", response_model=GenerateBlogResponse)
async def generate_blog(
    request: GenerateBlogRequest,
    http_request: Request,
    idempotency_key: Annotated[Optional[str], Header(alias="Idempotency-Key")] = None,
):
    """Accept a new blog generation request (standalone mode).

    Resolves standalone identity, reserves budget, creates a canonical session,
    and reuses the existing worker queue for execution.
    """
    ensure_csrf_header(http_request)
    _, identity = await _resolve_authenticated_identity(http_request)
    response = await _run_idempotent_action(
        user_scope=f"standalone:{identity.tenant_id}:{identity.end_user_id}",
        endpoint="/api/v1/blogs/generate",
        idempotency_key=idempotency_key,
        request_body=request.model_dump(exclude={"user_id"}, exclude_none=True),
        action=lambda: _create_generation_response(
            identity=identity,
            topic=request.topic,
            audience=request.audience,
            tone=request.tone,
        ),
        cacheable_error_statuses={402, 409, 503},
    )
    blog_generations_total.labels(status="initiated").inc()
    return response


@canonical_router.get("/blogs", response_model=BlogSessionListResponse)
async def list_my_blogs(
    request: Request,
    limit: int = 20,
    offset: int = 0,
    status: str | None = None,
):
    """List the authenticated user's blog sessions."""
    current_user = require_authenticated_user(request)
    tenant_id, end_user_id = await _resolve_standalone_budget(current_user.user_id)
    return await _list_blog_sessions(
        end_user_id=end_user_id,
        tenant_id=tenant_id,
        limit=min(max(limit, 1), 100),
        offset=max(offset, 0),
        status_filter=status,
    )


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
    idempotency_key: Annotated[Optional[str], Header(alias="Idempotency-Key")] = None,
):
    """Save outline edits or approve the outline and resume drafting."""
    try:
        ensure_csrf_header(http_request)
        current_user = require_authenticated_user(http_request)
        tenant_id, end_user_id = await _resolve_standalone_budget(current_user.user_id)
        normalized = request.model_copy(
            update={"reviewer_user_id": current_user.email or current_user.user_id}
        )
        return await _run_idempotent_action(
            user_scope=f"standalone:{tenant_id}:{end_user_id}",
            endpoint="/api/v1/blogs/{session_id}/outline/review",
            idempotency_key=idempotency_key,
            request_body={
                "session_id": int(session_id),
                **normalized.model_dump(exclude_none=True),
            },
            action=lambda: _submit_outline_review(
                session_id=int(session_id),
                request=normalized,
                external_user_id=current_user.user_id,
            ),
            cacheable_error_statuses={404, 409, 503},
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
    idempotency_key: Annotated[Optional[str], Header(alias="Idempotency-Key")] = None,
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

    normalized = request.model_copy(
        update={"reviewer_user_id": current_user.email or current_user.user_id}
    )
    tenant_id, end_user_id = await _resolve_standalone_budget(current_user.user_id)
    return await _run_idempotent_action(
        user_scope=f"standalone:{tenant_id}:{end_user_id}",
        endpoint="/api/v1/blogs/{session_id}/review",
        idempotency_key=idempotency_key,
        request_body={
            "session_id": blog_session_id,
            "version_id": version_id,
            **normalized.model_dump(exclude_none=True),
        },
        action=lambda: _submit_human_review(
            blog_session_id=blog_session_id,
            version_id=version_id,
            request=normalized,
            external_user_id=current_user.user_id,
        ),
        cacheable_error_statuses={402, 404, 409, 503},
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
        snapshot = await budget_service.get_snapshot(tenant_id, end_user_id)
        daily_cost_usd.labels(scope="user").set(snapshot.daily_spent_usd)
        return snapshot


# ---------------------------------------------------------------------------
# Internal service routes (Blogify server-to-server)
# ---------------------------------------------------------------------------


@internal_router.post("/blogs", response_model=GenerateBlogResponse)
async def service_generate_blog(
    request: ServiceGenerateBlogRequest,
    http_request: Request,
    x_internal_api_key: Annotated[Optional[str], Header()] = None,
    idempotency_key: Annotated[Optional[str], Header(alias="Idempotency-Key")] = None,
):
    """Accept blog generation request from Blogify backend (service mode).

    Requires:
        X-Internal-Api-Key: header with Blogify service API key
        tenant_id, end_user_id, request_id in body
    """
    await require_internal_service_client(
        http_request,
        x_internal_api_key,
        is_blog_request=True,
    )

    try:
        identity = await _resolve_service_identity(
            raw_api_key=x_internal_api_key,
            external_user_id=request.end_user_id,
            external_tenant_id=request.tenant_id,
        )
    except AdapterAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc))

    response = await _run_idempotent_action(
        user_scope=f"service:{identity.service_client_id}:{identity.tenant_id}:{identity.end_user_id}",
        endpoint="/internal/ai/blogs",
        idempotency_key=idempotency_key or request.request_id,
        request_body=request.model_dump(exclude_none=True),
        action=lambda: _create_generation_response(
            identity=identity,
            topic=request.topic,
            audience=request.audience,
            tone=request.tone,
            external_request_id=request.request_id,
            external_blog_id=request.external_blog_id,
        ),
        cacheable_error_statuses={402, 409, 503},
    )
    blog_generations_total.labels(status="initiated").inc()
    return response


@internal_router.get("/blogs/{session_id}", response_model=SessionStatusResponse)
async def service_get_session(
    session_id: str,
    request: Request,
    x_internal_api_key: Annotated[Optional[str], Header()] = None,
):
    """Get session status (service mode)."""
    await require_internal_service_client(request, x_internal_api_key)
    try:
        return await _get_session_status(int(session_id))
    except ValueError:
        raise HTTPException(status_code=400, detail="session_id must be an integer")


@internal_router.get("/blogs/{session_id}/outline", response_model=OutlineReviewView)
async def service_get_outline(
    session_id: str,
    request: Request,
    x_internal_api_key: Annotated[Optional[str], Header()] = None,
):
    await require_internal_service_client(request, x_internal_api_key)
    try:
        return await _get_outline_review(int(session_id))
    except ValueError:
        raise HTTPException(status_code=400, detail="session_id must be an integer")


@internal_router.get("/blogs/{session_id}/versions/latest", response_model=BlogVersionView)
async def service_get_latest_version(
    session_id: str,
    request: Request,
    x_internal_api_key: Annotated[Optional[str], Header()] = None,
):
    await require_internal_service_client(request, x_internal_api_key)
    try:
        return await _get_latest_version(int(session_id))
    except ValueError:
        raise HTTPException(status_code=400, detail="session_id must be an integer")


@internal_router.get("/blogs/{session_id}/content", response_model=BlogContentView)
async def service_get_content(
    session_id: str,
    request: Request,
    x_internal_api_key: Annotated[Optional[str], Header()] = None,
):
    await require_internal_service_client(request, x_internal_api_key)
    try:
        return await _get_content_view(int(session_id))
    except ValueError:
        raise HTTPException(status_code=400, detail="session_id must be an integer")


@internal_router.get("/blogs/{session_id}/detail", response_model=SessionDetailView)
async def service_get_detail(
    session_id: str,
    request: Request,
    x_internal_api_key: Annotated[Optional[str], Header()] = None,
):
    await require_internal_service_client(request, x_internal_api_key)
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
    http_request: Request,
    x_internal_api_key: Annotated[Optional[str], Header()] = None,
    idempotency_key: Annotated[Optional[str], Header(alias="Idempotency-Key")] = None,
):
    service_client = await require_internal_service_client(http_request, x_internal_api_key)
    try:
        blog_session_id = int(session_id)
        tenant_id, end_user_id = await _get_session_identity(blog_session_id)
        return await _run_idempotent_action(
            user_scope=f"service:{service_client.id}:{tenant_id}:{end_user_id}",
            endpoint="/internal/ai/blogs/{session_id}/outline/review",
            idempotency_key=idempotency_key,
            request_body={
                "session_id": blog_session_id,
                **request.model_dump(exclude_none=True),
            },
            action=lambda: _submit_outline_review(session_id=blog_session_id, request=request),
            cacheable_error_statuses={404, 409, 503},
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@internal_router.post("/blogs/{session_id}/review", response_model=HumanReviewDecision)
async def service_submit_review(
    session_id: str,
    version_id: int,
    request: HumanReviewRequest,
    http_request: Request,
    x_internal_api_key: Annotated[Optional[str], Header()] = None,
    idempotency_key: Annotated[Optional[str], Header(alias="Idempotency-Key")] = None,
):
    """Submit review (service mode). Mirrors standalone /review endpoint."""
    service_client = await require_internal_service_client(http_request, x_internal_api_key)

    try:
        blog_session_id = int(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="session_id must be an integer")
    tenant_id, end_user_id = await _get_session_identity(blog_session_id)
    return await _run_idempotent_action(
        user_scope=f"service:{service_client.id}:{tenant_id}:{end_user_id}",
        endpoint="/internal/ai/blogs/{session_id}/review",
        idempotency_key=idempotency_key,
        request_body={
            "session_id": blog_session_id,
            "version_id": version_id,
            **request.model_dump(exclude_none=True),
        },
        action=lambda: _submit_human_review(
            blog_session_id=blog_session_id,
            version_id=version_id,
            request=request,
        ),
        cacheable_error_statuses={402, 404, 409, 503},
    )


@internal_router.get("/budgets/{end_user_id}", response_model=BudgetSnapshot)
async def service_get_budget(
    request: Request,
    end_user_id: str,
    tenant_id: Optional[str] = None,
    x_internal_api_key: Annotated[Optional[str], Header()] = None,
):
    """Return budget snapshot for a specific end user (service mode)."""
    await require_internal_service_client(request, x_internal_api_key)

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
        snapshot = await budget_service.get_snapshot(
            resolved_tenant_id,
            resolved_end_user_id,
        )
        daily_cost_usd.labels(scope="user").set(snapshot.daily_spent_usd)
        return snapshot
