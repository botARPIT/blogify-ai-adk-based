"""Database repository for users, blogs, and cost records."""

from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from src.config.database_config import db_settings
from src.config.logging_config import get_logger
from src.models.orm_models import Base, Blog, CostRecord, User

logger = get_logger(__name__)

# Global engine and session factory (singleton pattern)
_engine = None
_async_session_factory = None


def get_engine():
    """Get or create the database engine singleton."""
    global _engine
    if _engine is None:
        _engine = create_async_engine(
            db_settings.database_url,
            pool_size=db_settings.database_pool_size,
            max_overflow=db_settings.database_max_overflow,
            pool_pre_ping=True,  # Verify connections before using
            pool_recycle=3600,  # Recycle connections after 1 hour
            echo=False,
        )
        logger.info("database_engine_created")
    return _engine


def get_session_factory():
    """Get or create the async session factory singleton."""
    global _async_session_factory
    if _async_session_factory is None:
        engine = get_engine()
        _async_session_factory = async_sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        logger.info("session_factory_created")
    return _async_session_factory


class DatabaseRepository:
    """Repository for database operations."""

    def __init__(self) -> None:
        """Initialize repository with shared engine and session factory."""
        self.engine = get_engine()
        self.async_session = get_session_factory()

    async def create_tables(self) -> None:
        """Create all database tables."""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("database_tables_created")

    async def get_or_create_user(self, user_id: str, email: str | None = None) -> User:
        """Get existing user or create new one."""
        async with self.async_session() as session:
            async with session.begin():
                result = await session.execute(select(User).where(User.user_id == user_id))
                user = result.scalar_one_or_none()

                if user is None:
                    user = User(user_id=user_id, email=email)
                    session.add(user)
                    await session.flush()
                    logger.info("user_created", user_id=user_id)

                return user

    async def create_blog(
        self, user_id: str, session_id: str, topic: str, audience: str | None = None
    ) -> Blog:
        """Create new blog record."""
        async with self.async_session() as session:
            async with session.begin():
                blog = Blog(
                    user_id=user_id,
                    session_id=session_id,
                    topic=topic,
                    audience=audience,
                    status="in_progress",
                )
                session.add(blog)
                await session.flush()
                logger.info("blog_created", blog_id=blog.id, session_id=session_id)
                return blog

    async def update_blog(
        self,
        session_id: str,
        title: str | None = None,
        content: str | None = None,
        word_count: int | None = None,
        sources_count: int | None = None,
        status: str | None = None,
        total_cost_usd: float | None = None,
        total_tokens: int | None = None,
    ) -> Blog | None:
        """Update blog record."""
        async with self.async_session() as db_session:
            async with db_session.begin():
                result = await db_session.execute(
                    select(Blog).where(Blog.session_id == session_id)
                )
                blog = result.scalar_one_or_none()

                if blog:
                    if title is not None:
                        blog.title = title
                    if content is not None:
                        blog.content = content
                    if word_count is not None:
                        blog.word_count = word_count
                    if sources_count is not None:
                        blog.sources_count = sources_count
                    if status is not None:
                        blog.status = status
                    if total_cost_usd is not None:
                        blog.total_cost_usd = total_cost_usd
                    if total_tokens is not None:
                        blog.total_tokens = total_tokens

                    if status == "completed":
                        blog.completed_at = datetime.utcnow()

                    await db_session.flush()
                    logger.info("blog_updated", blog_id=blog.id, status=blog.status)

                return blog

    async def create_cost_record(
        self,
        user_id: str,
        session_id: str,
        agent_name: str,
        model_name: str,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        cost_usd: float,
        blog_id: int | None = None,
        latency_ms: int | None = None,
        success: bool = True,
        error_message: str | None = None,
    ) -> CostRecord:
        """Create cost tracking record."""
        async with self.async_session() as session:
            async with session.begin():
                cost_record = CostRecord(
                    user_id=user_id,
                    blog_id=blog_id,
                    session_id=session_id,
                    agent_name=agent_name,
                    model_name=model_name,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    cost_usd=cost_usd,
                    latency_ms=latency_ms,
                    success=success,
                    error_message=error_message,
                )
                session.add(cost_record)
                await session.flush()
                logger.info(
                    "cost_record_created",
                    agent=agent_name,
                    cost_usd=cost_usd,
                    tokens=total_tokens,
                )
                return cost_record

    async def get_user_daily_cost(self, user_id: str) -> float:
        """Get user's total cost for today."""
        async with self.async_session() as session:
            today = datetime.utcnow().date()
            result = await session.execute(
                select(CostRecord).where(
                    CostRecord.user_id == user_id,
                    CostRecord.created_at >= datetime.combine(today, datetime.min.time()),
                )
            )
            records = result.scalars().all()
            return sum(r.cost_usd for r in records)

    async def get_user_daily_blog_count(self, user_id: str) -> int:
        """Get number of blogs user generated today."""
        async with self.async_session() as session:
            today = datetime.utcnow().date()
            result = await session.execute(
                select(Blog).where(
                    Blog.user_id == user_id,
                    Blog.created_at >= datetime.combine(today, datetime.min.time()),
                )
            )
            blogs = result.scalars().all()
            return len(blogs)

    async def get_blog_by_session(self, session_id: str) -> Blog | None:
        """Get blog by session ID."""
        async with self.async_session() as session:
            result = await session.execute(
                select(Blog).where(Blog.session_id == session_id)
            )
            return result.scalar_one_or_none()

    async def update_blog_stage(
        self, session_id: str, stage: str, stage_data: dict
    ) -> Blog | None:
        """Update blog pipeline stage and data."""
        async with self.async_session() as db_session:
            async with db_session.begin():
                result = await db_session.execute(
                    select(Blog).where(Blog.session_id == session_id)
                )
                blog = result.scalar_one_or_none()

                if blog:
                    blog.current_stage = stage
                    blog.stage_data = stage_data
                    await db_session.flush()
                    logger.info("blog_stage_updated", session_id=session_id, stage=stage)

                return blog

    async def get_blog(self, blog_id: int) -> Blog | None:
        """Get blog by ID."""
        async with self.async_session() as session:
            result = await session.execute(
                select(Blog).where(Blog.id == blog_id)
            )
            return result.scalar_one_or_none()

    async def close(self) -> None:
        """Close database connections."""
        if self.engine:
            await self.engine.dispose()
            logger.info("database_engine_closed")



# Global instance
db_repository = DatabaseRepository()
