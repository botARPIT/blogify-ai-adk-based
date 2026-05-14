"""SessionReservationRepository — per-session reservation tracking."""

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.orm_models import SessionReservation


class SessionReservationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        blog_session_id: int,
        reserved_usd: Decimal,
        reserved_tokens: int,
    ) -> SessionReservation:
        reservation = SessionReservation(
            blog_session_id=blog_session_id,
            reserved_usd=reserved_usd,
            reserved_tokens=reserved_tokens,
        )
        self._session.add(reservation)
        await self._session.flush()
        return reservation

    async def get_by_session(self, blog_session_id: int) -> SessionReservation | None:
        result = await self._session.execute(
            select(SessionReservation).where(SessionReservation.blog_session_id == blog_session_id)
        )
        return result.scalar_one_or_none()

    async def mark_committed(self, blog_session_id: int) -> SessionReservation | None:
        reservation = await self.get_by_session(blog_session_id)
        if reservation:
            reservation.released_at = reservation.created_at
            await self._session.flush()
        return reservation

    async def mark_released(self, blog_session_id: int) -> SessionReservation | None:
        reservation = await self.get_by_session(blog_session_id)
        if reservation:
            await self._session.flush()
        return reservation
