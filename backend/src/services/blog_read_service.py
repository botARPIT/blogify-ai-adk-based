"""Query-side projections for the blog HTTP API."""

from datetime import datetime, timedelta, timezone
from typing import Any

from src.config.api_config import DAILY_BLOG_GENERATION_LIMIT
from src.config.budget_config import MAX_TOKENS_PER_USER, MODEL_PRICING
from src.models.orm_models import BlogSessionStatus
from src.models.repositories.agent_run_repository import AgentRunRepository
from src.models.repositories.blog_quota_repository import BlogQuotaRepository
from src.models.repositories.blog_review_event_repository import BlogReviewEventRepository
from src.models.repositories.blog_session_repository import BlogSessionRepository
from src.models.repositories.blog_version_repository import BlogVersionRepository
from src.models.repositories.budget_account_repository import BudgetAccountRepository
from src.models.schemas import (
    AgentRunMetrics,
    BlogContentView,
    BlogInsightsResponse,
    BlogSessionDetail,
    BlogSessionListItem,
    BlogSessionMetrics,
    BlogSessionPage,
    BlogVersionMetrics,
    BlogVersionView,
    BudgetResponse,
    HumanReviewEventView,
    OutlineReviewView,
    ResearchDataSchema,
    ResearchSourceView,
    SessionInfo,
    SessionStatusResponse,
)


class BlogReadService:
    """Build API response models from persisted blog workflow state."""

    def __init__(self, session: Any) -> None:
        self._sessions = BlogSessionRepository(session)
        self._versions = BlogVersionRepository(session)
        self._runs = AgentRunRepository(session)
        self._reviews = BlogReviewEventRepository(session)
        self._accounts = BudgetAccountRepository(session)
        self._quotas = BlogQuotaRepository(session)

    async def list_sessions(
        self,
        user_id: int,
        page: int,
        page_size: int,
        statuses: list[BlogSessionStatus] | None,
        query: str | None,
    ) -> BlogSessionPage:
        sessions, total = await self._sessions.list_for_user(
            user_id, page=page, page_size=page_size, statuses=statuses, search=query
        )
        return BlogSessionPage(
            items=[
                BlogSessionListItem(
                    session_id=s.id,
                    topic=s.topic,
                    audience=s.audience,
                    tone=s.tone,
                    status=s.status,
                    current_stage=s.current_stage,
                    created_at=s.created_at,
                    completed_at=s.completed_at,
                    cost_usd=float(s.budget_spent_usd or 0),
                )
                for s in sessions
            ],
            page=page,
            page_size=page_size,
            total=total,
            total_pages=(total + page_size - 1) // page_size,
        )

    async def insights(self, user_id: int, days: int) -> BlogInsightsResponse:
        first_day = datetime.now(timezone.utc).date() - timedelta(days=days - 1)
        data = await self._sessions.get_insights_for_user(
            user_id, since=datetime.combine(first_day, datetime.min.time(), tzinfo=timezone.utc)
        )
        by_day = {row.day: row for row in data["daily"]}
        return BlogInsightsResponse(
            days=days,
            total_generated=data["total_generated"],
            completed_count=data["completed_count"],
            failed_count=data["failed_count"],
            total_cost_usd=data["total_cost_usd"],
            daily=[
                {
                    "date": day,
                    "generated_count": getattr(by_day.get(day), "generated_count", 0),
                    "cost_usd": float(getattr(by_day.get(day), "cost_usd", 0) or 0),
                }
                for day in (first_day + timedelta(days=i) for i in range(days))
            ],
            blog_costs=[
                {
                    "session_id": item.id,
                    "topic": item.topic,
                    "status": item.status,
                    "created_at": item.created_at,
                    "cost_usd": float(item.budget_spent_usd or 0),
                }
                for item in data["blog_costs"]
            ],
        )

    async def outline(self, user_id: int, session_id: int) -> OutlineReviewView:
        blog = await self._owned_session(user_id, session_id)
        version = await self._versions.get_active_for_session(session_id)
        outline = (
            (version.approved_outline or version.outline_data) if version else blog.outline_data
        )
        if not outline:
            raise ValueError("No outline available")
        return OutlineReviewView(
            session_id=blog.id,
            status=blog.status,
            current_stage=blog.current_stage,
            topic=blog.topic,
            audience=blog.audience,
            outline=outline,
        )

    async def budget(self, user_id: int) -> BudgetResponse:
        snapshot = await self._accounts.get_snapshot(user_id)
        price_per_token = MODEL_PRICING["gemini-2.5-flash"] / 1000
        available = float(snapshot["available_usd"])
        return BudgetResponse(
            balance_usd=float(snapshot["balance_usd"]),
            balance_tokens=min(MAX_TOKENS_PER_USER, int(available / price_per_token)) if price_per_token else 0,
            daily_blog_limit_left=await self._quotas.get_remaining(
                user_id, DAILY_BLOG_GENERATION_LIMIT, datetime.now(timezone.utc).date()
            ),
            daily_blog_limit=DAILY_BLOG_GENERATION_LIMIT,
        )

    async def status(self, user_id: int, session_id: int) -> SessionStatusResponse:
        blog = await self._owned_session(user_id, session_id)
        latest = await self._runs.get_latest_for_session(session_id)
        return SessionStatusResponse(
            session_id=blog.id,
            status=blog.status,
            current_stage=blog.current_stage,
            current_agent=latest.stage_name if latest and latest.status == "RUNNING" else None,
            topic=blog.topic,
            created_at=blog.created_at,
        )

    async def detail(self, user_id: int, session_id: int) -> BlogSessionMetrics:
        blog = await self._owned_session(user_id, session_id)
        version = await self._versions.get_latest_for_session(session_id)
        runs = await self._runs.get_for_session(session_id)
        content = (version.final_content if version else None) or blog.final_content
        sources = self._sources(version.research_data if version else None)
        latest = None
        if content:
            latest = BlogVersionMetrics(
                version_id=version.id if version else 1,
                version_number=version.version_number if version else 1,
                title=(version.title if version else None) or blog.topic,
                content_markdown=content,
                word_count=len(content.split()),
                sources_count=len(sources),
                created_at=version.updated_at if version else blog.updated_at,
            )
        return BlogSessionMetrics(
            session=SessionInfo(
                session_id=blog.id,
                status=blog.status,
                current_stage=blog.current_stage,
                topic=blog.topic,
                audience=blog.audience,
                created_at=blog.created_at,
                updated_at=blog.updated_at,
                completed_at=blog.completed_at,
                budget_spent_usd=float(blog.budget_spent_usd),
                budget_spent_tokens=blog.budget_spent_tokens,
                requires_human_review=blog.status
                in {"AWAITING_OUTLINE_REVIEW", "AWAITING_FINAL_REVIEW"},
                current_version_number=version.version_number
                if content and version
                else (1 if content else None),
            ),
            total_cost_usd=float(blog.budget_spent_usd),
            total_tokens=sum(run.total_tokens for run in runs),
            total_words=len(content.split()) if content else 0,
            outline=(version.approved_outline if version else None) or blog.outline_data,
            latest_version=latest,
            agent_runs=[
                AgentRunMetrics(
                    run_id=run.id,
                    stage=run.stage_name,
                    status=run.status.value if hasattr(run.status, "value") else run.status,
                    total_tokens=run.total_tokens,
                    cost_usd=float(run.cost_usd),
                    latency_ms=run.latency_ms,
                    started_at=run.started_at,
                    completed_at=run.completed_at,
                    error_message=run.error_message,
                )
                for run in runs
            ],
            review_events=[
                HumanReviewEventView(
                    event_id=event.id,
                    session_id=event.blog_session_id,
                    version_id=event.blog_version_id,
                    reviewer_user_id=str(event.reviewer_user_id),
                    action=event.action,
                    feedback_text=event.feedback_text,
                    created_at=event.created_at,
                )
                for event in await self._reviews.get_for_session(session_id)
            ],
        )

    async def session(self, user_id: int, session_id: int) -> BlogSessionDetail:
        blog = await self._owned_session(user_id, session_id)
        version = await self._versions.get_latest_for_session(session_id)
        return BlogSessionDetail(
            session_id=blog.id,
            topic=blog.topic,
            audience=blog.audience,
            tone=blog.tone,
            status=blog.status,
            current_stage=blog.current_stage,
            outline_data=(version.approved_outline if version else None) or blog.outline_data,
            final_content=(version.final_content if version else None) or blog.final_content,
            budget_reserved_usd=float(blog.budget_reserved_usd),
            budget_spent_usd=float(blog.budget_spent_usd),
            agent_runs=[
                {
                    "stage": run.stage_name,
                    "tokens": run.total_tokens,
                    "cost_usd": float(run.cost_usd),
                    "status": run.status.value if hasattr(run.status, "value") else run.status,
                }
                for run in await self._runs.get_for_session(session_id)
            ],
            created_at=blog.created_at,
            updated_at=blog.updated_at,
        )

    async def content(self, user_id: int, session_id: int) -> BlogContentView:
        blog = await self._owned_session(user_id, session_id)
        version = await self._versions.get_latest_for_session(session_id)
        content = (version.final_content if version else None) or blog.final_content
        if not content:
            raise ValueError("Final blog content is not available for this session")
        sources = self._sources(version.research_data if version else None)
        return BlogContentView(
            session_id=blog.id,
            version_id=version.id if version else 1,
            title=(version.title if version else None) or blog.topic,
            content_markdown=content,
            word_count=len(content.split()),
            sources_count=len(sources),
            sources=sources,
            topic=blog.topic,
            audience=blog.audience,
            status=blog.status,
        )

    async def latest_version(self, user_id: int, session_id: int) -> BlogVersionView:
        blog = await self._owned_session(user_id, session_id)
        version = await self._versions.get_latest_for_session(session_id)
        if version is None or not version.final_content:
            raise ValueError("No blog version found")
        return BlogVersionView(
            version_id=version.id,
            session_id=blog.id,
            version_number=version.version_number,
            title=version.title or blog.topic,
            content_markdown=version.final_content,
            word_count=len(version.final_content.split()),
            sources_count=len(self._sources(version.research_data)),
            created_at=version.updated_at,
        )

    async def export_markdown(self, user_id: int, session_id: int) -> tuple[str, str]:
        blog = await self._owned_session(user_id, session_id)
        if blog.status != BlogSessionStatus.COMPLETED.value:
            raise ValueError("Only completed blogs can be exported")
        version = await self._versions.get_latest_for_session(session_id)
        content = (version.final_content if version else None) or blog.final_content
        if not content:
            raise ValueError("Final blog content is not available for this session")
        return content, (version.title if version else None) or blog.topic or f"blog-{session_id}"

    async def _owned_session(self, user_id: int, session_id: int):
        blog = await self._sessions.get_by_id(session_id)
        if blog is None or blog.user_id != user_id:
            raise ValueError("Session not found")
        return blog

    @staticmethod
    def _sources(research_data: object) -> list[ResearchSourceView]:
        if not isinstance(research_data, dict):
            return []
        try:
            research = ResearchDataSchema.model_validate(research_data)
        except ValueError:
            return []
        return [
            ResearchSourceView(title=source.title, url=source.url, provider=source.provider)
            for source in research.sources
        ]
