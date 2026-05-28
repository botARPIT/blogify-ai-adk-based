"""BudgetService — V2 budget operations backed by budget_accounts + session_reservations."""

from decimal import Decimal

from src.config.budget_config import ESTIMATED_TOKENS_PER_BLOG
from src.models.orm_models import BudgetEntryType
from src.models.repositories.blog_session_repository import BlogSessionRepository
from src.models.repositories.budget_account_repository import BudgetAccountRepository
from src.models.repositories.budget_repository import BudgetRepository
from src.models.repositories.session_reservation_repository import SessionReservationRepository


class BudgetService:
    """Owns all budget operations.

    Invariants:
    - budget_accounts.balance_usd - budget_accounts.reserved_usd = available balance
    - session_reservations has exactly one row per in-flight session
    - budget_ledger is an append-only audit trail; it is NOT queried for balance
    - Caller must hold Redis lock keyed f"budget_lock:{user_id}" before check_and_reserve
    """

    def __init__(
        self,
        budget_repo: BudgetRepository,
        session_repo: BlogSessionRepository,
        account_repo: BudgetAccountRepository,
        reservation_repo: SessionReservationRepository,
    ) -> None:
        self._budget_repo = budget_repo
        self._session_repo = session_repo
        self._account_repo = account_repo
        self._reservation_repo = reservation_repo

    async def check_and_reserve(self, user_id: int, blog_session_id: int) -> None:
        """Check available balance and create a budget reservation.

        1. apply_reserve on budget_accounts (raises InsufficientBudgetError if short)
        2. Write RESERVE entry to ledger (audit)
        3. Create session_reservations row
        4. Update blog_sessions.budget_reserved_* columns
        """
        estimated_usd = Decimal(str(ESTIMATED_TOKENS_PER_BLOG)) * Decimal("0.00002")
        estimated_tokens = ESTIMATED_TOKENS_PER_BLOG

        await self._account_repo.apply_reserve(user_id=user_id, amount_usd=estimated_usd)

        await self._budget_repo.write_entry(
            user_id=user_id,
            blog_session_id=blog_session_id,
            agent_run_id=None,
            entry_type=BudgetEntryType.RESERVE,
            tokens=-estimated_tokens,
            amount_usd=-estimated_usd,
            note="Budget reservation for blog generation",
        )

        await self._reservation_repo.create(
            blog_session_id=blog_session_id,
            reserved_usd=estimated_usd,
            reserved_tokens=estimated_tokens,
        )

        session = await self._session_repo.get_by_id(blog_session_id)
        if session:
            session.budget_reserved_tokens = estimated_tokens
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
        """Record actual stage cost.

        - Writes COMMIT entry to ledger (idempotency-guarded)
        - Updates blog_sessions.budget_spent_* columns
        """
        existing = await self._budget_repo.get_ledger_for_session(blog_session_id)
        for entry in existing:
            if (
                entry.agent_run_id == agent_run_id
                and entry.entry_type == BudgetEntryType.COMMIT.value
            ):
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

    async def release_excess(self, *, user_id: int, blog_session_id: int) -> None:
        """Release the unspent portion of the reservation after a successful run.

        Reads reserved_usd from session_reservations to avoid stale-session bugs.
        """
        reservation = await self._reservation_repo.get_by_session(blog_session_id)
        if not reservation:
            return

        reserved_usd = reservation.reserved_usd
        reserved_tokens = reservation.reserved_tokens

        # get actual spends from blog_sessions
        session = await self._session_repo.get_by_id(blog_session_id)
        actual_usd = session.budget_spent_usd if session else Decimal("0")
        actual_tokens = session.budget_spent_tokens if session else 0
        await self._account_repo.apply_commit(
            user_id=user_id,
            reserved_usd=reserved_usd,
            actual_usd=actual_usd,
        )

        await self._reservation_repo.mark_committed(blog_session_id)

        await self._budget_repo.write_entry(
            user_id=user_id,
            blog_session_id=blog_session_id,
            agent_run_id=None,
            entry_type=BudgetEntryType.RELEASE,
            tokens=actual_tokens,
            amount_usd=actual_usd,
            note="Excess budget released after successful generation",
        )

    async def release_all(self, *, user_id: int, blog_session_id: int) -> None:
        """Release the entire reservation on failure."""
        reservation = await self._reservation_repo.get_by_session(blog_session_id)
        if not reservation or reservation.reserved_usd == Decimal("0"):
            return

        reserved_usd = reservation.reserved_usd
        reserved_tokens = reservation.reserved_tokens

        await self._account_repo.apply_release(user_id=user_id, reserved_usd=reserved_usd)

        await self._reservation_repo.mark_released(blog_session_id)

        await self._budget_repo.write_entry(
            user_id=user_id,
            blog_session_id=blog_session_id,
            agent_run_id=None,
            entry_type=BudgetEntryType.RELEASE,
            tokens=reserved_tokens,
            amount_usd=reserved_usd,
            note="All budget released after generation failure",
        )
