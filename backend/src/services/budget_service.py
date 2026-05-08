"""BudgetService — V1 budget operations."""

from decimal import Decimal
from typing import Optional

from src.config.budget_config import ESTIMATED_TOKENS_PER_BLOG, get_model_cost
from src.models.orm_models import BudgetEntryType
from src.models.repositories.blog_session_repository import BlogSessionRepository
from src.models.repositories.budget_repository import BudgetRepository


class InsufficientBudgetError(Exception):
    pass


class BudgetService:
    """
    Owns all budget operations. Never opens DB connections.
    Takes budget_repo and session_repo as constructor arguments.
    """

    def __init__(
        self,
        budget_repo: BudgetRepository,
        session_repo: BlogSessionRepository,
    ) -> None:
        self._budget_repo = budget_repo
        self._session_repo = session_repo

    async def check_and_reserve(
        self, user_id: int, blog_session_id: int
    ) -> None:
        """
        Check user balance and reserve estimated budget.
        
        NOTE: Caller must hold a Redis lock keyed on f"budget_lock:{user_id}"
        before calling this method to prevent race conditions.
        """
        balance = await self._budget_repo.get_balance(user_id)
        balance_usd = balance["balance_usd"]

        estimated_usd = Decimal(str(ESTIMATED_TOKENS_PER_BLOG)) * Decimal("0.00002")

        if balance_usd < estimated_usd:
            raise InsufficientBudgetError("Insufficient budget")

        await self._budget_repo.write_entry(
            user_id=user_id,
            blog_session_id=blog_session_id,
            agent_run_id=None,
            entry_type=BudgetEntryType.RESERVE,
            tokens=-ESTIMATED_TOKENS_PER_BLOG,
            amount_usd=-estimated_usd,
            note="Budget reservation for blog generation",
        )

        session = await self._session_repo.get_by_id(blog_session_id)
        if session:
            session.budget_reserved_tokens = ESTIMATED_TOKENS_PER_BLOG
            session.budget_reserved_usd = estimated_usd
            await self._session_repo.session.flush()

    async def commit_stage(
        self,
        *,
        user_id: int,
        blog_session_id: int,
        agent_run_id: int,
        actual_tokens: int,
        actual_usd: Decimal,
    ) -> None:
        existing = await self._budget_repo.get_ledger_for_session(blog_session_id)
        for entry in existing:
            if entry.agent_run_id == agent_run_id and entry.entry_type == BudgetEntryType.COMMIT.value:
                return

        await self._budget_repo.write_entry(
            user_id=user_id,
            blog_session_id=blog_session_id,
            agent_run_id=agent_run_id,
            entry_type=BudgetEntryType.COMMIT,
            tokens=-actual_tokens,
            amount_usd=-actual_usd,
            note=f"Commit for agent run {agent_run_id}",
        )

        session = await self._session_repo.get_by_id(blog_session_id)
        if session:
            session.budget_spent_tokens += actual_tokens
            session.budget_spent_usd += actual_usd
            await self._session_repo.session.flush()

    async def release_excess(
        self, *, user_id: int, blog_session_id: int
    ) -> None:
        reserved = abs(await self._budget_repo.get_reserved_for_session(blog_session_id))
        committed = abs(await self._budget_repo.get_committed_for_session(blog_session_id))

        excess = reserved - committed
        if excess <= 0:
            return

        reserved_tokens = abs(await self._budget_repo.get_reserved_for_session(blog_session_id))
        committed_tokens = abs(await self._budget_repo.get_committed_for_session(blog_session_id))
        excess_tokens = reserved_tokens - committed_tokens

        await self._budget_repo.write_entry(
            user_id=user_id,
            blog_session_id=blog_session_id,
            agent_run_id=None,
            entry_type=BudgetEntryType.RELEASE,
            tokens=excess_tokens,
            amount_usd=excess,
            note="Excess budget released",
        )

    async def release_all(
        self, *, user_id: int, blog_session_id: int
    ) -> None:
        session = await self._session_repo.get_by_id(blog_session_id)
        if not session or session.budget_reserved_tokens == 0:
            return

        reserved_tokens = session.budget_reserved_tokens
        reserved_usd = session.budget_reserved_usd

        await self._budget_repo.write_entry(
            user_id=user_id,
            blog_session_id=blog_session_id,
            agent_run_id=None,
            entry_type=BudgetEntryType.RELEASE,
            tokens=reserved_tokens,
            amount_usd=reserved_usd,
            note="Full budget release on failure",
        )

    async def get_balance_snapshot(self, user_id: int) -> dict:
        balance = await self._budget_repo.get_balance(user_id)
        return {
            "balance_usd": float(balance["balance_usd"]),
            "balance_tokens": balance["balance_tokens"],
        }