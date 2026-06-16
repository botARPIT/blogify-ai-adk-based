"""Blog routes — generation, listing, reviews, budget."""

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.auth import AuthenticatedUser, get_current_user
from src.core.database import get_db_session
from src.core.redis_pool import get_redis_client
from src.core.task_queue import task_queue
from src.guards.input_guard import InputGuard
from src.models.repositories.blog_session_repository import BlogSessionRepository
from src.models.repositories.blog_version_repository import BlogVersionRepository
from src.models.repositories.budget_account_repository import BudgetAccountRepository
from src.models.repositories.budget_repository import BudgetRepository
from src.models.repositories.research_sources_repository import ResearchSourcesRepository
from src.models.repositories.session_reservation_repository import SessionReservationRepository
from src.models.schemas import (
    AgentRunMetrics,
    BlogContentView,
    BlogSessionDetail,
    BlogSessionListItem,
    BlogSessionMetrics,
    BlogVersionMetrics,
    BlogVersionView,
    BudgetResponse,
    FinalReviewRequest,
    GenerateRequest,
    GenerateResponse,
    OutlineFrontendDecision,
    OutlineFrontendRequest,
    OutlineReviewRequest,
    OutlineReviewView,
    SessionInfo,
    SessionStatusResponse,
)
from src.services.blog_service import BlogService
from src.services.budget_service import BudgetService
from src.services.exceptions import InsufficientBudgetError, SessionTerminalError

router = APIRouter(prefix="/blogs", tags=["blogs"])


def get_authenticated_user_id(current_user: AuthenticatedUser) -> int:
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return int(current_user.user_id)


input_guard = InputGuard()


@router.post("/generate", status_code=202, response_model=GenerateResponse)
async def generate_blog(
    body: GenerateRequest,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    current_user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    is_valid, error_msg = input_guard.validate(body.topic, body.audience, body.tone)
    if not is_valid:
        raise HTTPException(status_code=400, detail=error_msg)
    effective_idempotency_key = idempotency_key or body.idempotency_key
    user_id = get_authenticated_user_id(current_user)
    session_repo = BlogSessionRepository(session)
    budget_repo = BudgetRepository(session)
    account_repo = BudgetAccountRepository(session)
    reservation_repo = SessionReservationRepository(session)
    budget_service = BudgetService(budget_repo, session_repo, account_repo, reservation_repo)
    redis_client = await get_redis_client()
    version_repo = BlogVersionRepository(session)
    blog_service = BlogService(session_repo, version_repo, budget_service, task_queue, redis_client)

    try:
        result = await blog_service.create_generation(
            user_id=user_id,
            topic=body.topic,
            audience=body.audience,
            tone=body.tone,
            idempotency_key=effective_idempotency_key,
        )
        return GenerateResponse(
            session_id=result.id,
            status=result.status,
            adk_session_id=result.adk_session_id,
            created_at=result.created_at,
        )
    except SessionTerminalError:
        raise HTTPException(
            status_code=409,
            detail={
                "error_code": "SESSION_TERMINAL",
                "message": "This request ID has already completed. Generate a new Idempotency-Key to retry.",
            },
        )
    except InsufficientBudgetError as e:
        raise HTTPException(status_code=402, detail=str(e))
    except ValueError as e:
        error_msg = str(e)
        if "already has an active" in error_msg:
            raise HTTPException(status_code=409, detail=error_msg)
        raise HTTPException(status_code=400, detail=error_msg)


@router.get("/", response_model=list[BlogSessionListItem])
async def list_blogs(
    current_user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    user_id = get_authenticated_user_id(current_user)
    session_repo = BlogSessionRepository(session)
    version_repo = BlogVersionRepository(session)
    budget_repo = BudgetRepository(session)
    account_repo = BudgetAccountRepository(session)
    reservation_repo = SessionReservationRepository(session)
    budget_service = BudgetService(budget_repo, session_repo, account_repo, reservation_repo)
    redis_client = await get_redis_client()
    blog_service = BlogService(session_repo, version_repo, budget_service, task_queue, redis_client)

    sessions = await blog_service.get_user_sessions(user_id)
    return [
        BlogSessionListItem(
            session_id=s.id,
            topic=s.topic,
            audience=s.audience,
            tone=s.tone,
            status=s.status,
            current_stage=s.current_stage,
            created_at=s.created_at,
            completed_at=s.completed_at,
        )
        for s in sessions
    ]


@router.get("/{session_id}/outline", response_model=OutlineReviewView)
async def get_outline(
    session_id: int,
    current_user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    user_id = get_authenticated_user_id(current_user)
    session_repo = BlogSessionRepository(session)
    version_repo = BlogVersionRepository(session)

    blog_session = await session_repo.get_by_id(session_id)
    if not blog_session or blog_session.user_id != user_id:
        raise HTTPException(status_code=404, detail="Session not found")

    active_version = await version_repo.get_active_for_session(session_id)
    outline = None
    if active_version:
        outline = active_version.approved_outline or active_version.outline_data
    if not outline:
        outline = blog_session.outline_data
    if not outline:
        raise HTTPException(status_code=404, detail="No outline available")

    return OutlineReviewView(
        session_id=blog_session.id,
        status=blog_session.status,
        current_stage=blog_session.current_stage,
        topic=blog_session.topic,
        audience=blog_session.audience,
        feedback_text=None,
        outline=outline,
    )


@router.post("/{session_id}/outline/review", response_model=OutlineFrontendDecision)
async def submit_outline_review_frontend(
    session_id: int,
    body: OutlineFrontendRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    user_id = get_authenticated_user_id(current_user)
    session_repo = BlogSessionRepository(session)
    budget_repo = BudgetRepository(session)
    account_repo = BudgetAccountRepository(session)
    reservation_repo = SessionReservationRepository(session)
    budget_service = BudgetService(budget_repo, session_repo, account_repo, reservation_repo)
    redis_client = await get_redis_client()
    version_repo = BlogVersionRepository(session)
    blog_service = BlogService(session_repo, version_repo, budget_service, task_queue, redis_client)

    if body.action == "revise" and body.edited_outline:
        approved_outline = body.edited_outline
    elif body.action == "approve" and body.edited_outline:
        approved_outline = body.edited_outline
    else:
        raise HTTPException(status_code=400, detail="Invalid action")

    try:
        result = await blog_service.submit_outline_review(
            user_id=user_id,
            session_id=session_id,
            approved_outline=approved_outline,
            feedback_text=body.feedback_text,
        )
        return OutlineFrontendDecision(
            session_id=result.id,
            action=body.action,
            new_status=result.status,
            current_stage=result.current_stage,
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.get("/budget", response_model=BudgetResponse)
async def get_budget(
    current_user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    from src.config.budget_config import MODEL_PRICING

    user_id = get_authenticated_user_id(current_user)
    session_repo = BlogSessionRepository(session)
    account_repo = BudgetAccountRepository(session)

    snapshot = await account_repo.get_snapshot(user_id)

    # Derive token equivalent from available USD at Gemini Flash rate
    price_per_token = MODEL_PRICING["gemini-2.5-flash"] / 1000  # USD per token
    available_usd = float(snapshot["available_usd"])
    balance_tokens = int(available_usd / price_per_token) if price_per_token > 0 else 0

    active_count = await session_repo.count_active_for_user(user_id)
    daily_limit = 1
    daily_limit_left = max(0, daily_limit - active_count)

    return BudgetResponse(
        balance_usd=float(snapshot["balance_usd"]),
        balance_tokens=balance_tokens,
        daily_blog_limit_left=daily_limit_left,
    )


@router.get("/{session_id}/status", response_model=SessionStatusResponse)
async def get_session_status(
    session_id: int,
    current_user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    user_id = get_authenticated_user_id(current_user)
    session_repo = BlogSessionRepository(session)

    blog_session = await session_repo.get_by_id(session_id)
    if not blog_session or blog_session.user_id != user_id:
        raise HTTPException(status_code=404, detail="Session not found")

    from sqlalchemy import desc, select

    from src.models.orm_models import AgentRun

    result = await session.execute(
        select(AgentRun)
        .where(AgentRun.blog_session_id == session_id)
        .order_by(desc(AgentRun.started_at))
        .limit(1)
    )
    latest_agent_run = result.scalar_one_or_none()

    current_agent = None
    if latest_agent_run and latest_agent_run.status == "RUNNING":
        current_agent = latest_agent_run.stage_name

    return SessionStatusResponse(
        session_id=blog_session.id,
        status=blog_session.status,
        current_stage=blog_session.current_stage,
        current_agent=current_agent,
        topic=blog_session.topic,
        created_at=blog_session.created_at,
    )


@router.get("/{session_id}/detail", response_model=BlogSessionMetrics)
async def get_session_detail(
    session_id: int,
    current_user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    user_id = get_authenticated_user_id(current_user)
    session_repo = BlogSessionRepository(session)
    version_repo = BlogVersionRepository(session)
    sources_repo = ResearchSourcesRepository(session)

    blog_session = await session_repo.get_by_id(session_id)
    if not blog_session or blog_session.user_id != user_id:
        raise HTTPException(status_code=404, detail="Session not found")

    from sqlalchemy import select

    from src.models.orm_models import AgentRun

    result = await session.execute(select(AgentRun).where(AgentRun.blog_session_id == session_id))
    agent_runs = result.scalars().all()

    latest_version_row = await version_repo.get_latest_for_session(session_id)
    latest_content = (
        latest_version_row.final_content if latest_version_row and latest_version_row.final_content else blog_session.final_content
    )
    total_tokens = sum(ar.total_tokens for ar in agent_runs)
    total_words = len(latest_content.split()) if latest_content else 0
    sources_count = await sources_repo.count_for_session(session_id)

    latest_version = None
    if latest_content:
        latest_version = BlogVersionMetrics(
            version_id=latest_version_row.id if latest_version_row else 1,
            version_number=latest_version_row.version_number if latest_version_row else 1,
            title=(latest_version_row.title if latest_version_row else None) or blog_session.topic,
            content_markdown=latest_content,
            word_count=total_words,
            sources_count=sources_count,
            editor_status="completed",
            created_by="system",
            created_at=latest_version_row.updated_at if latest_version_row else blog_session.updated_at,
        )

    # Determine if content is available (completed status)
    has_content = blog_session.status == "COMPLETED" and bool(latest_content)

    return BlogSessionMetrics(
        session=SessionInfo(
            session_id=blog_session.id,
            status=blog_session.status,
            current_stage=blog_session.current_stage,
            topic=blog_session.topic,
            audience=blog_session.audience,
            created_at=blog_session.created_at,
            updated_at=blog_session.updated_at,
            completed_at=blog_session.completed_at,
            budget_spent_usd=float(blog_session.budget_spent_usd),
            budget_spent_tokens=blog_session.budget_spent_tokens,
            iteration_count=0,
            requires_human_review=blog_session.status
            in ("AWAITING_OUTLINE_REVIEW", "AWAITING_FINAL_REVIEW"),
            remaining_revision_iterations=0,
            current_version_number=latest_version_row.version_number if has_content and latest_version_row else (1 if has_content else None),
        ),
        total_cost_usd=float(blog_session.budget_spent_usd),
        total_tokens=total_tokens,
        total_words=total_words,
        outline=(latest_version_row.approved_outline if latest_version_row else None) or blog_session.outline_data,
        latest_version=latest_version,
        agent_runs=[
            AgentRunMetrics(
                run_id=ar.id,
                stage=ar.stage_name,
                status=ar.status.value if hasattr(ar.status, "value") else ar.status,
                total_tokens=ar.total_tokens,
                cost_usd=float(ar.cost_usd),
                latency_ms=ar.latency_ms,
                started_at=ar.started_at,
                completed_at=ar.completed_at,
                error_message=ar.error_message,
            )
            for ar in agent_runs
        ],
        review_events=[],
    )


@router.get("/{session_id}", response_model=BlogSessionDetail)
async def get_blog(
    session_id: int,
    current_user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    user_id = get_authenticated_user_id(current_user)
    session_repo = BlogSessionRepository(session)
    version_repo = BlogVersionRepository(session)
    budget_repo = BudgetRepository(session)
    account_repo = BudgetAccountRepository(session)
    reservation_repo = SessionReservationRepository(session)
    budget_service = BudgetService(budget_repo, session_repo, account_repo, reservation_repo)
    redis_client = await get_redis_client()
    version_repo = BlogVersionRepository(session)
    blog_service = BlogService(session_repo, version_repo, budget_service, task_queue, redis_client)

    try:
        s = await blog_service.get_session(user_id, session_id)
    except ValueError as e:
        error_msg = str(e)
        if "not found" in error_msg:
            raise HTTPException(status_code=404, detail=error_msg)
        if "Access denied" in error_msg:
            raise HTTPException(status_code=403, detail=error_msg)
        raise HTTPException(status_code=400, detail=error_msg)

    from sqlalchemy import select

    from src.models.orm_models import AgentRun

    result = await session.execute(select(AgentRun).where(AgentRun.blog_session_id == session_id))
    agent_runs = result.scalars().all()
    latest_version = await version_repo.get_latest_for_session(session_id)

    return BlogSessionDetail(
        session_id=s.id,
        topic=s.topic,
        audience=s.audience,
        tone=s.tone,
        status=s.status,
        current_stage=s.current_stage,
        outline_data=(latest_version.approved_outline if latest_version else None) or s.outline_data,
        final_content=(latest_version.final_content if latest_version else None) or s.final_content,
        budget_reserved_usd=float(s.budget_reserved_usd),
        budget_spent_usd=float(s.budget_spent_usd),
        agent_runs=[
            {
                "stage": ar.stage_name,
                "tokens": ar.total_tokens,
                "cost_usd": float(ar.cost_usd),
                "status": ar.status,
            }
            for ar in agent_runs
        ],
        created_at=s.created_at,
        updated_at=s.updated_at,
    )


@router.post("/{session_id}/outline-review")
async def submit_outline_review(
    session_id: int,
    body: OutlineReviewRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    user_id = get_authenticated_user_id(current_user)
    session_repo = BlogSessionRepository(session)
    budget_repo = BudgetRepository(session)
    account_repo = BudgetAccountRepository(session)
    reservation_repo = SessionReservationRepository(session)
    budget_service = BudgetService(budget_repo, session_repo, account_repo, reservation_repo)
    redis_client = await get_redis_client()
    version_repo = BlogVersionRepository(session)
    blog_service = BlogService(session_repo, version_repo, budget_service, task_queue, redis_client)

    try:
        result = await blog_service.submit_outline_review(
            user_id=user_id,
            session_id=session_id,
            approved_outline=body.approved_outline,
            feedback_text=body.feedback_text,
        )
        return {"session_id": result.id, "status": result.status}
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/{session_id}/final-review")
async def submit_final_review(
    session_id: int,
    body: FinalReviewRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    user_id = get_authenticated_user_id(current_user)
    session_repo = BlogSessionRepository(session)
    budget_repo = BudgetRepository(session)
    account_repo = BudgetAccountRepository(session)
    reservation_repo = SessionReservationRepository(session)
    budget_service = BudgetService(budget_repo, session_repo, account_repo, reservation_repo)
    redis_client = await get_redis_client()
    version_repo = BlogVersionRepository(session)
    blog_service = BlogService(session_repo, version_repo, budget_service, task_queue, redis_client)

    try:
        result = await blog_service.submit_final_review(
            user_id=user_id,
            session_id=session_id,
            action=body.action,
            feedback_text=body.feedback_text,
        )
        return {"session_id": result.id, "status": result.status}
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.get("/{session_id}/content", response_model=BlogContentView)
async def get_content(
    session_id: int,
    current_user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    user_id = get_authenticated_user_id(current_user)
    session_repo = BlogSessionRepository(session)
    version_repo = BlogVersionRepository(session)
    sources_repo = ResearchSourcesRepository(session)

    blog_session = await session_repo.get_by_id(session_id)
    if not blog_session or blog_session.user_id != user_id:
        raise HTTPException(status_code=404, detail="Session not found")

    latest_version = await version_repo.get_latest_for_session(session_id)
    content = (latest_version.final_content if latest_version else None) or blog_session.final_content
    if not content:
        raise HTTPException(
            status_code=404,
            detail="Final blog content is not available for this session",
        )

    word_count = len(content.split()) if content else 0
    sources_count = await sources_repo.count_for_session(session_id)

    return BlogContentView(
        session_id=blog_session.id,
        version_id=latest_version.id if latest_version else 1,
        title=(latest_version.title if latest_version else None) or blog_session.topic,
        content_markdown=content,
        word_count=word_count,
        sources_count=sources_count,
        topic=blog_session.topic,
        audience=blog_session.audience,
        status=blog_session.status,
    )


@router.get("/{session_id}/versions/latest", response_model=BlogVersionView)
async def get_latest_version(
    session_id: int,
    current_user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    user_id = get_authenticated_user_id(current_user)
    session_repo = BlogSessionRepository(session)
    version_repo = BlogVersionRepository(session)
    sources_repo = ResearchSourcesRepository(session)

    blog_session = await session_repo.get_by_id(session_id)
    if not blog_session or blog_session.user_id != user_id:
        raise HTTPException(status_code=404, detail="Session not found")

    latest_version = await version_repo.get_latest_for_session(session_id)
    if latest_version is None or not latest_version.final_content:
        raise HTTPException(
            status_code=404,
            detail="No blog version found",
        )

    sources_count = await sources_repo.count_for_session(session_id)

    return BlogVersionView(
        version_id=latest_version.id,
        session_id=blog_session.id,
        version_number=latest_version.version_number,
        source_type="final",
        title=latest_version.title or blog_session.topic,
        content_markdown=latest_version.final_content,
        word_count=len(latest_version.final_content.split()),
        sources_count=sources_count,
        editor_status="completed",
        created_by="system",
        created_at=latest_version.updated_at,
    )
