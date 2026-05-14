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
        blog_session_id: int,
        url: str | None = None,
        title: str | None = None,
        snippet: str | None = None,
    ) -> ResearchSource:
        source = ResearchSource(
            blog_session_id=blog_session_id,
            url=url,
            title=title,
            snippet=snippet,
        )
        self.session.add(source)
        await self.session.flush()
        return source

    async def create_many(
        self,
        blog_session_id: int,
        sources: list[dict],
    ) -> list[ResearchSource]:
        created = []
        for src in sources:
            source = ResearchSource(
                blog_session_id=blog_session_id,
                url=src.get("url"),
                title=src.get("title"),
                snippet=src.get("snippet") or src.get("content"),
            )
            self.session.add(source)
            created.append(source)
        await self.session.flush()
        return created

    async def get_for_session(self, blog_session_id: int) -> list[ResearchSource]:
        result = await self.session.execute(
            select(ResearchSource).where(ResearchSource.blog_session_id == blog_session_id)
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
