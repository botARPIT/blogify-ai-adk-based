"""BlogSessionRepository — V1 simplified repository."""

from datetime import datetime, timezone

from sqlalchemy import Date, case, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.orm_models import BlogSession, BlogSessionStatus


class BlogSessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @property
    def session(self) -> AsyncSession:
        return self._session

    async def create(
        self,
        *,
        user_id: int,
        topic: str,
        audience: str,
        tone: str,
        adk_session_id: str,
        idempotency_key: str | None = None,
    ) -> BlogSession:
        blog_session = BlogSession(
            user_id=user_id,
            topic=topic,
            audience=audience,
            tone=tone,
            status=BlogSessionStatus.QUEUED,
            job_phase="fresh_generation",
            adk_session_id=adk_session_id,
            idempotency_key=idempotency_key,
        )
        self._session.add(blog_session)
        await self._session.flush()
        return blog_session

    async def get_by_id(self, session_id: int) -> BlogSession | None:
        result = await self._session.execute(
            select(BlogSession).where(BlogSession.id == session_id)
        )
        return result.scalar_one_or_none()

    async def get_by_id_for_update(self, session_id: int) -> BlogSession | None:
        result = await self._session.execute(
            select(BlogSession).where(BlogSession.id == session_id).with_for_update()
        )
        return result.scalar_one_or_none()

    async def get_by_idempotency_key(self, user_id: int, key: str) -> BlogSession | None:
        result = await self._session.execute(
            select(BlogSession).where(
                BlogSession.user_id == user_id,
                BlogSession.idempotency_key == key,
            )
        )
        return result.scalar_one_or_none()

    async def get_for_user(self, user_id: int, limit: int = 20) -> list[BlogSession]:
        result = await self._session.execute(
            select(BlogSession)
            .where(BlogSession.user_id == user_id)
            .order_by(BlogSession.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_for_user(
        self,
        user_id: int,
        *,
        page: int,
        page_size: int,
        statuses: list[BlogSessionStatus] | None = None,
        search: str | None = None,
    ) -> tuple[list[BlogSession], int]:
        conditions = [BlogSession.user_id == user_id]
        if statuses:
            conditions.append(BlogSession.status.in_([status.value for status in statuses]))
        if search:
            pattern = f"%{search.strip()}%"
            conditions.append(
                or_(BlogSession.topic.ilike(pattern), BlogSession.audience.ilike(pattern))
            )

        total = await self._session.scalar(select(func.count(BlogSession.id)).where(*conditions))
        result = await self._session.execute(
            select(BlogSession)
            .where(*conditions)
            .order_by(BlogSession.created_at.desc(), BlogSession.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(result.scalars().all()), int(total or 0)

    async def get_insights_for_user(
        self,
        user_id: int,
        *,
        since: datetime,
    ) -> dict:
        conditions = [BlogSession.user_id == user_id, BlogSession.created_at >= since]
        unsuccessful_statuses = [
            BlogSessionStatus.FAILED.value,
            BlogSessionStatus.REJECTED.value,
            BlogSessionStatus.AGENT_REJECTED.value,
            BlogSessionStatus.CANCELLED.value,
        ]
        non_failed_conditions = [
            *conditions,
            BlogSession.status.notin_(unsuccessful_statuses),
        ]
        summary = await self._session.execute(
            select(
                func.sum(case((BlogSession.status.notin_(unsuccessful_statuses), 1), else_=0)),
                func.sum(
                    case((BlogSession.status == BlogSessionStatus.COMPLETED.value, 1), else_=0)
                ),
                func.sum(
                    case(
                        (
                            BlogSession.status.in_(
                                [
                                    *unsuccessful_statuses,
                                ]
                            ),
                            1,
                        ),
                        else_=0,
                    )
                ),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                BlogSession.status.notin_(unsuccessful_statuses),
                                BlogSession.budget_spent_usd,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ),
            ).where(*conditions)
        )
        total_generated, completed_count, failed_count, total_cost_usd = summary.one()

        daily_result = await self._session.execute(
            select(
                cast(BlogSession.created_at, Date).label("day"),
                func.count(BlogSession.id).label("generated_count"),
                func.coalesce(func.sum(BlogSession.budget_spent_usd), 0).label("cost_usd"),
            )
            .where(*non_failed_conditions)
            .group_by(cast(BlogSession.created_at, Date))
            .order_by(cast(BlogSession.created_at, Date))
        )
        recent_result = await self._session.execute(
            select(BlogSession)
            .where(*non_failed_conditions)
            .order_by(BlogSession.created_at.desc(), BlogSession.id.desc())
            .limit(12)
        )
        return {
            "total_generated": int(total_generated or 0),
            "completed_count": int(completed_count or 0),
            "failed_count": int(failed_count or 0),
            "total_cost_usd": float(total_cost_usd or 0),
            "daily": list(daily_result.all()),
            "blog_costs": list(recent_result.scalars().all()),
        }

    async def count_active_for_user(self, user_id: int) -> int:
        active = [s.value for s in BlogSessionStatus.active_states()]
        result = await self._session.execute(
            select(BlogSession).where(
                BlogSession.user_id == user_id,
                BlogSession.status.in_(active),
            )
        )
        return len(result.scalars().all())

    async def update_status(
        self,
        session_id: int,
        status: BlogSessionStatus,
        current_stage: str | None = None,
    ) -> None:
        """Update session status with state machine validation."""
        blog_session = await self.get_by_id(session_id)
        if not blog_session:
            return

        # Validate transition against the state machine
        current = BlogSessionStatus(blog_session.status)
        BlogSessionStatus.validate_transition(current, status)

        blog_session.status = status
        if current_stage:
            blog_session.current_stage = current_stage
        blog_session.updated_at = datetime.now(timezone.utc)
        await self._session.flush()

    async def recover_stale_processing_session(
        self,
        session_id: int,
        *,
        current_stage: str | None = "requeued_by_reaper",
    ) -> BlogSession | None:
        """Reaper-only recovery path for dead in-flight work.

        This bypasses the normal public transition validator because stale-lease
        recovery is a separate control path from user/worker workflow moves.
        """
        blog_session = await self.get_by_id(session_id)
        if not blog_session:
            return None

        current = BlogSessionStatus(blog_session.status)
        if current in BlogSessionStatus.terminal_states():
            return blog_session
        if current != BlogSessionStatus.PROCESSING:
            from src.core.errors import InvalidStateTransition

            raise InvalidStateTransition(
                from_status=current.value,
                to_status=BlogSessionStatus.QUEUED.value,
            )

        blog_session.status = BlogSessionStatus.QUEUED
        blog_session.current_stage = current_stage
        blog_session.updated_at = datetime.now(timezone.utc)
        await self._session.flush()
        return blog_session

    async def update_job_phase(self, session_id: int, job_phase: str) -> None:
        """Persist the job phase for reaper recovery."""
        blog_session = await self.get_by_id(session_id)
        if blog_session:
            blog_session.job_phase = job_phase
            blog_session.updated_at = datetime.now(timezone.utc)
            await self._session.flush()

    async def sync_active_version_fields(
        self,
        session_id: int,
        *,
        outline_data: dict | None = None,
        final_content: str | None = None,
        adk_session_id: str | None = None,
        active_blog_version_id: int | None = None,
    ) -> None:
        blog_session = await self.get_by_id(session_id)
        if not blog_session:
            return

        if outline_data is not None:
            blog_session.outline_data = outline_data
        if final_content is not None:
            blog_session.final_content = final_content
        if adk_session_id is not None:
            blog_session.adk_session_id = adk_session_id
        if active_blog_version_id is not None:
            blog_session.active_blog_version_id = active_blog_version_id

        blog_session.updated_at = datetime.now(timezone.utc)
        await self._session.flush()

    async def save_final_content(self, session_id: int, content: str) -> None:
        blog_session = await self.get_by_id(session_id)
        if blog_session:
            blog_session.final_content = content
            blog_session.updated_at = datetime.now(timezone.utc)
            await self._session.flush()

    async def increment_reap_count(self, session_id: int) -> int:
        blog_session = await self.get_by_id(session_id)
        if blog_session:
            blog_session.reap_count += 1
            blog_session.updated_at = datetime.now(timezone.utc)
            await self._session.flush()
            return blog_session.reap_count
        return 0

    async def mark_failed(self, session_id: int, reason: str) -> None:
        """Mark session as FAILED with state machine validation."""
        blog_session = await self.get_by_id(session_id)
        if not blog_session:
            return

        # Validate the transition to FAILED
        current = BlogSessionStatus(blog_session.status)
        BlogSessionStatus.validate_transition(current, BlogSessionStatus.FAILED)

        blog_session.status = BlogSessionStatus.FAILED
        blog_session.failure_reason = reason
        blog_session.failed_at = datetime.now(timezone.utc)
        blog_session.updated_at = datetime.now(timezone.utc)
        await self._session.flush()

    async def mark_agent_rejected(self, session_id: int, reason: str) -> None:
        """Persist a terminal rejection made by the automated intent gate."""
        blog_session = await self.get_by_id(session_id)
        if not blog_session:
            return

        current = BlogSessionStatus(blog_session.status)
        BlogSessionStatus.validate_transition(current, BlogSessionStatus.AGENT_REJECTED)

        blog_session.status = BlogSessionStatus.AGENT_REJECTED
        blog_session.current_stage = "intent_rejected"
        blog_session.job_phase = None
        blog_session.failure_reason = reason
        blog_session.updated_at = datetime.now(timezone.utc)
        await self._session.flush()
