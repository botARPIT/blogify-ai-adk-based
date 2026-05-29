"""BlogSessionRepository — V1 simplified repository."""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.orm_models import BlogSession, BlogSessionStatus


class BlogSessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        print("BlogSessionRepository initialized!, this call is from blog session repository", flush=True)
        self._session = session

    @property
    def session(self) -> AsyncSession:
        print("Getting session!, this call is from blog session repository", flush=True)
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
        print("Creating blog session!, this call is from blog session repository", flush=True)
        blog_session = BlogSession(
            user_id=user_id,
            topic=topic,
            audience=audience,
            tone=tone,
            status=BlogSessionStatus.QUEUED,
            adk_session_id=adk_session_id,
            idempotency_key=idempotency_key,
        )
        self._session.add(blog_session)
        await self._session.flush()
        return blog_session

    async def get_by_id(self, session_id: int) -> BlogSession | None:
        print("Getting blog session by id!, this call is from blog session repository", flush=True)
        result = await self._session.execute(
            select(BlogSession).where(BlogSession.id == session_id)
        )
        return result.scalar_one_or_none()

    async def get_by_idempotency_key(self, user_id: int, key: str) -> BlogSession | None:
        print("Getting blog session by idempotency key!, this call is from blog session repository", flush=True)
        result = await self._session.execute(
            select(BlogSession).where(
                BlogSession.user_id == user_id,
                BlogSession.idempotency_key == key,
            )
        )
        return result.scalar_one_or_none()

    async def get_for_user(self, user_id: int, limit: int = 20) -> list[BlogSession]:
        print("Getting blog sessions for user!, this call is from blog session repository", flush=True)
        result = await self._session.execute(
            select(BlogSession)
            .where(BlogSession.user_id == user_id)
            .order_by(BlogSession.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def count_active_for_user(self, user_id: int) -> int:
        print("Counting active sessions for user!, this call is from blog session repository", flush=True)
        result = await self._session.execute(
            select(BlogSession).where(
                BlogSession.user_id == user_id,
                BlogSession.status.in_(
                    [
                        BlogSessionStatus.QUEUED,
                        BlogSessionStatus.PROCESSING,
                        BlogSessionStatus.AWAITING_OUTLINE_REVIEW,
                        BlogSessionStatus.AWAITING_FINAL_REVIEW,
                    ]
                ),
            )
        )
        return len(result.scalars().all())

    async def update_status(
        self,
        session_id: int,
        status: BlogSessionStatus,
        current_stage: str | None = None,
    ) -> None:
        print("Updating blog session status!, this call is from blog session repository", flush=True)
        blog_session = await self.get_by_id(session_id)
        if blog_session:
            blog_session.status = status
            if current_stage:
                blog_session.current_stage = current_stage
            blog_session.updated_at = datetime.now(timezone.utc)
            await self._session.flush()

    async def save_outline(
        self,
        session_id: int,
        outline_data: dict,
        invocation_id: str,
        confirmation_request_id: str,
    ) -> None:
        print("Saving outline!, this call is from blog session repository", flush=True)
        blog_session = await self.get_by_id(session_id)
        print("Outline saved!, this call is from blog session repository", flush=True)
        if blog_session:
            blog_session.outline_data = outline_data
            print("Outline data saved!, this call is from blog session repository", flush=True)
            blog_session.invocation_id = invocation_id
            print("Invocation id saved!, this call is from blog session repository", flush=True)
            blog_session.confirmation_request_id = confirmation_request_id
            print("Confirmation request id saved!, this call is from blog session repository", flush=True)
            blog_session.updated_at = datetime.now(timezone.utc)
            print("Updated at saved!, this call is from blog session repository", flush=True)
            await self._session.flush()
            print("Flush completed!, this call is from blog session repository", flush=True)

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
        blog_session = await self.get_by_id(session_id)
        if blog_session:
            blog_session.status = BlogSessionStatus.FAILED
            blog_session.failure_reason = reason
            blog_session.failed_at = datetime.now(timezone.utc)
            blog_session.updated_at = datetime.now(timezone.utc)
            await self._session.flush()
