"""BudgetAccountRepository — atomic O(1) balance operations on budget_accounts."""

from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.orm_models import BudgetAccount
from src.services.exceptions import InsufficientBudgetError


class BudgetAccountRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @property
    def session(self) -> AsyncSession:
        return self._session

    async def get_or_create(self, user_id: int) -> BudgetAccount:
        """Return the BudgetAccount for user_id, creating a zero-balance row if absent."""
        result = await self._session.execute(
            select(BudgetAccount).where(BudgetAccount.user_id == user_id)
        )
        account = result.scalar_one_or_none()
        if account is None:
            account = BudgetAccount(
                user_id=user_id,
                balance_usd=Decimal("0"),
                reserved_usd=Decimal("0"),
                total_granted_usd=Decimal("0"),
                total_spent_usd=Decimal("0"),
            )
            self._session.add(account)
            await self._session.flush()
        return account

    async def apply_grant(self, *, user_id: int, amount_usd: Decimal) -> BudgetAccount:
        """Credit the account: balance_usd += amount_usd, total_granted_usd += amount_usd."""
        account = await self.get_or_create(user_id)
        account.balance_usd += amount_usd
        account.total_granted_usd += amount_usd
        await self._session.flush()
        return account

    async def apply_reserve(self, *, user_id: int, amount_usd: Decimal) -> BudgetAccount:
        """Reserve budget: reserved_usd += amount_usd.

        Raises InsufficientBudgetError if available_usd < amount_usd.
        Caller MUST hold the Redis budget_lock:{user_id} before calling.
        """
        account = await self.get_or_create(user_id)
        available = account.balance_usd - account.reserved_usd
        if available < amount_usd:
            raise InsufficientBudgetError(
                f"Insufficient budget: need ${amount_usd:.4f}, available ${available:.4f}"
            )
        account.reserved_usd += amount_usd
        await self._session.flush()
        return account

    async def apply_commit(
        self,
        *,
        user_id: int,
        reserved_usd: Decimal,
        actual_usd: Decimal,
    ) -> BudgetAccount:
        """Settle a reservation at terminal success.

        - reserved_usd -= reserved_usd (release the hold)
        - balance_usd  -= actual_usd   (deduct what was actually spent)
        - total_spent_usd += actual_usd
        """
        account = await self.get_or_create(user_id)
        # Clamp to avoid going negative due to float rounding
        account.reserved_usd = max(Decimal("0"), account.reserved_usd - reserved_usd)
        account.balance_usd -= actual_usd
        account.total_spent_usd += actual_usd
        await self._session.flush()
        return account

    async def apply_release(self, *, user_id: int, reserved_usd: Decimal) -> BudgetAccount:
        """Release an un-spent reservation (excess or full failure release).

        reserved_usd -= reserved_usd (balance_usd unchanged — the money was never spent).
        """
        account = await self.get_or_create(user_id)
        account.reserved_usd = max(Decimal("0"), account.reserved_usd - reserved_usd)
        await self._session.flush()
        return account

    async def get_snapshot(self, user_id: int) -> dict:
        """Return a dict snapshot of the account for API responses."""
        account = await self.get_or_create(user_id)
        available = account.balance_usd - account.reserved_usd
        return {
            "balance_usd": account.balance_usd,
            "reserved_usd": account.reserved_usd,
            "available_usd": max(Decimal("0"), available),
            "total_granted_usd": account.total_granted_usd,
            "total_spent_usd": account.total_spent_usd,
        }
