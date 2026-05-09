"""SessionReservationRepository — per-session reservation tracking."""

from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.orm_models import ReservationStatus, SessionReservation


class SessionReservationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        user_id: int,
        blog_session_id: int,
        reserved_usd: Decimal,
        reserved_tokens: int,
    ) -> SessionReservation:
        reservation = SessionReservation(
            user_id=user_id,
            blog_session_id=blog_session_id,
            reserved_usd=reserved_usd,
            reserved_tokens=reserved_tokens,
            actual_usd=Decimal("0"),
            actual_tokens=0,
            status=ReservationStatus.ACTIVE.value,
        )
        self._session.add(reservation)
        await self._session.flush()
        return reservation

    async def get_by_session(self, blog_session_id: int) -> Optional[SessionReservation]:
        result = await self._session.execute(
            select(SessionReservation).where(
                SessionReservation.blog_session_id == blog_session_id
            )
        )
        return result.scalar_one_or_none()

    async def accumulate_actual(
        self,
        *,
        blog_session_id: int,
        actual_usd: Decimal,
        actual_tokens: int,
    ) -> Optional[SessionReservation]:
        """Accumulate stage costs into the reservation row during generation."""
        reservation = await self.get_by_session(blog_session_id)
        if reservation:
            reservation.actual_usd += actual_usd
            reservation.actual_tokens += actual_tokens
            await self._session.flush()
        return reservation

    async def mark_committed(self, blog_session_id: int) -> Optional[SessionReservation]:
        """Mark reservation as COMMITTED (terminal success)."""
        reservation = await self.get_by_session(blog_session_id)
        if reservation:
            reservation.status = ReservationStatus.COMMITTED.value
            await self._session.flush()
        return reservation

    async def mark_released(self, blog_session_id: int) -> Optional[SessionReservation]:
        """Mark reservation as RELEASED (terminal failure / excess release)."""
        reservation = await self.get_by_session(blog_session_id)
        if reservation:
            reservation.status = ReservationStatus.RELEASED.value
            await self._session.flush()
        return reservation
