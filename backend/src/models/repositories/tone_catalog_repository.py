"""Read access to the curated tone catalog."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.orm_models import ToneCatalog


class ToneCatalogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_tones(self) -> list[ToneCatalog]:
        result = await self._session.execute(
            select(ToneCatalog).order_by(ToneCatalog.sort_order, ToneCatalog.id)
        )
        return list(result.scalars().all())
