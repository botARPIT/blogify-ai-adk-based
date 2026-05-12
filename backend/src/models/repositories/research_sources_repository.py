"""Repository for research sources from Tavily."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.orm_models import ResearchSource


class ResearchSourcesRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def session(self) -> AsyncSession:
        return self.session

    async def create(
        self,
        user_id: int,
        blog_session_id: int,
        title: str,
        url: str,
        content: str | None = None,
        score: float = 0.0,
        topic: str | None = None,
    ) -> ResearchSource:
        source = ResearchSource(
            user_id=user_id,
            blog_session_id=blog_session_id,
            title=title,
            url=url,
            content=content,
            score=score,
            topic=topic,
        )
        self.session.add(source)
        await self.session.flush()
        return source

    async def create_many(
        self,
        user_id: int,
        blog_session_id: int,
        sources: list[dict],
    ) -> list[ResearchSource]:
        created = []
        for src in sources:
            source = ResearchSource(
                user_id=user_id,
                blog_session_id=blog_session_id,
                title=src.get("title", ""),
                url=src.get("url", ""),
                content=src.get("content"),
                score=src.get("score", 0.0),
                topic=src.get("topic"),
            )
            self.session.add(source)
            created.append(source)
        await self.session.flush()
        return created

    async def get_for_session(self, blog_session_id: int) -> list[ResearchSource]:
        result = await self.session.execute(
            select(ResearchSource)
            .where(ResearchSource.blog_session_id == blog_session_id)
            .order_by(ResearchSource.score.desc())
        )
        return list(result.scalars().all())

    async def count_for_session(self, blog_session_id: int) -> int:
        result = await self.session.execute(
            select(ResearchSource).where(ResearchSource.blog_session_id == blog_session_id)
        )
        return len(list(result.scalars().all()))

    async def delete_for_session(self, blog_session_id: int) -> None:
        result = await self.session.execute(
            select(ResearchSource).where(ResearchSource.blog_session_id == blog_session_id)
        )
        sources = result.scalars().all()
        for source in sources:
            await self.session.delete(source)
        await self.session.flush()
