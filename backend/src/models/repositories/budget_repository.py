"""BudgetRepository — V1 simplified budget ledger."""

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.orm_models import BudgetEntryType, BudgetLedger


class BudgetRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @property
    def session(self) -> AsyncSession:
        return self._session

    async def write_entry(
        self,
        *,
        user_id: int,
        blog_session_id: int | None,
        agent_run_id: int | None,
        entry_type: BudgetEntryType,
        tokens: int,
        amount_usd: Decimal,
        note: str | None = None,
    ) -> BudgetLedger:
        entry = BudgetLedger(
            user_id=user_id,
            blog_session_id=blog_session_id,
            agent_run_id=agent_run_id,
            entry_type=entry_type.value,
            tokens=tokens,
            amount_usd=amount_usd,
            note=note,
        )
        self._session.add(entry)
        await self._session.flush()
        return entry

    async def get_ledger_for_session(self, blog_session_id: int) -> list[BudgetLedger]:
        result = await self._session.execute(
            select(BudgetLedger)
            .where(BudgetLedger.blog_session_id == blog_session_id)
            .order_by(BudgetLedger.created_at)
        )
        return list(result.scalars().all())

    async def get_reserved_for_session(self, blog_session_id: int) -> Decimal:
        result = await self._session.execute(
            select(func.coalesce(func.sum(BudgetLedger.amount_usd), 0)).where(
                BudgetLedger.blog_session_id == blog_session_id,
                BudgetLedger.entry_type == BudgetEntryType.RESERVE.value,
            )
        )
        return result.scalar() or Decimal("0")

    async def get_committed_for_session(self, blog_session_id: int) -> Decimal:
        result = await self._session.execute(
            select(func.coalesce(func.sum(BudgetLedger.amount_usd), 0)).where(
                BudgetLedger.blog_session_id == blog_session_id,
                BudgetLedger.entry_type == BudgetEntryType.COMMIT.value,
            )
        )
        return result.scalar() or Decimal("0")
