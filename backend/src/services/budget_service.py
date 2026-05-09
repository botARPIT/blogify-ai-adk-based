"""BudgetService — V2 budget operations backed by budget_accounts + session_reservations."""

from decimal import Decimal
from typing import Optional

from src.config.budget_config import ESTIMATED_TOKENS_PER_BLOG, get_model_cost
from src.models.orm_models import BudgetEntryType
from src.models.repositories.blog_session_repository import BlogSessionRepository
from src.models.repositories.budget_account_repository import BudgetAccountRepository
from src.models.repositories.budget_repository import BudgetRepository
from src.models.repositories.session_reservation_repository import SessionReservationRepository
from src.services.exceptions import InsufficientBudgetError  # re-export for callers


class BudgetService:
    """Owns all budget operations.

    Invariants:
    - budget_accounts.balance_usd − budget_accounts.reserved_usd = available balance
    - session_reservations has exactly one ACTIVE row per in-flight session
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

    # ------------------------------------------------------------------
    # Reservation
    # ------------------------------------------------------------------

    async def check_and_reserve(self, user_id: int, blog_session_id: int) -> None:
        """Check available balance and create a budget reservation.

        1. apply_reserve on budget_accounts (raises InsufficientBudgetError if short)
        2. Write RESERVE entry to ledger (audit)
        3. Create session_reservations row
        4. Update blog_sessions.budget_reserved_* columns
        """
        estimated_usd = Decimal(str(ESTIMATED_TOKENS_PER_BLOG)) * Decimal("0.00002")
        estimated_tokens = ESTIMATED_TOKENS_PER_BLOG

        # 1. Atomic reserve — raises InsufficientBudgetError if short
        await self._account_repo.apply_reserve(user_id=user_id, amount_usd=estimated_usd)

        # 2. Ledger audit entry
        await self._budget_repo.write_entry(
            user_id=user_id,
            blog_session_id=blog_session_id,
            agent_run_id=None,
            entry_type=BudgetEntryType.RESERVE,
            tokens=-estimated_tokens,
            amount_usd=-estimated_usd,
            note="Budget reservation for blog generation",
        )

        # 3. Session reservation row
        await self._reservation_repo.create(
            user_id=user_id,
            blog_session_id=blog_session_id,
            reserved_usd=estimated_usd,
            reserved_tokens=estimated_tokens,
        )

        # 4. Update session snapshot columns
        session = await self._session_repo.get_by_id(blog_session_id)
        if session:
            session.budget_reserved_tokens = estimated_tokens
            session.budget_reserved_usd = estimated_usd
            await self._session_repo.session.flush()

    # ------------------------------------------------------------------
    # Commit (called per-stage as actual cost is known)
    # ------------------------------------------------------------------

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
        - Accumulates actual_usd onto session_reservations row
        - Updates blog_sessions.budget_spent_* columns
        NOTE: Does NOT update budget_accounts yet — that happens at terminal commit/release.
        """
        # Idempotency guard — skip if already committed for this agent run
        existing = await self._budget_repo.get_ledger_for_session(blog_session_id)
        for entry in existing:
            if entry.agent_run_id == agent_run_id and entry.entry_type == BudgetEntryType.COMMIT.value:
                return

        # Ledger audit entry
        await self._budget_repo.write_entry(
            user_id=user_id,
            blog_session_id=blog_session_id,
            agent_run_id=agent_run_id,
            entry_type=BudgetEntryType.COMMIT,
            tokens=-actual_tokens,
            amount_usd=-actual_usd,
            note=f"Commit for agent run {agent_run_id}",
        )

        # Accumulate into reservation row
        await self._reservation_repo.accumulate_actual(
            blog_session_id=blog_session_id,
            actual_usd=actual_usd,
            actual_tokens=actual_tokens,
        )

        # Update session snapshot columns
        session = await self._session_repo.get_by_id(blog_session_id)
        if session:
            session.budget_spent_tokens += actual_tokens
            session.budget_spent_usd += actual_usd
            await self._session_repo.session.flush()

    # ------------------------------------------------------------------
    # Terminal: release excess after success
    # ------------------------------------------------------------------

    async def release_excess(self, *, user_id: int, blog_session_id: int) -> None:
        """Release the unspent portion of the reservation after a successful run.

        - Reads reserved_usd and actual_usd from session_reservations (not ledger sum)
        - Calls apply_commit on budget_accounts to settle the reservation
        - Calls apply_release on budget_accounts for any excess
        - Marks reservation as COMMITTED
        - Writes RELEASE entry to ledger for excess (if any)
        """
        reservation = await self._reservation_repo.get_by_session(blog_session_id)
        if not reservation:
            return

        reserved_usd = reservation.reserved_usd
        actual_usd = reservation.actual_usd
        excess_usd = max(Decimal("0"), reserved_usd - actual_usd)

        reserved_tokens = reservation.reserved_tokens
        actual_tokens = reservation.actual_tokens
        excess_tokens = max(0, reserved_tokens - actual_tokens)

        # Settle the full reservation on the account
        await self._account_repo.apply_commit(
            user_id=user_id,
            reserved_usd=reserved_usd,
            actual_usd=actual_usd,
        )

        # Mark reservation terminal
        await self._reservation_repo.mark_committed(blog_session_id)

        # Write excess RELEASE to ledger if there is any
        if excess_usd > Decimal("0"):
            await self._budget_repo.write_entry(
                user_id=user_id,
                blog_session_id=blog_session_id,
                agent_run_id=None,
                entry_type=BudgetEntryType.RELEASE,
                tokens=excess_tokens,
                amount_usd=excess_usd,
                note="Excess budget released after successful generation",
            )

    # ------------------------------------------------------------------
    # Terminal: release all on failure
    # ------------------------------------------------------------------

    async def release_all(self, *, user_id: int, blog_session_id: int) -> None:
        """Release the entire reservation on failure.

        Reads reserved_usd from session_reservations (not session columns) to avoid
        the stale-session bug where session.budget_reserved_tokens == 0.
        """
        reservation = await self._reservation_repo.get_by_session(blog_session_id)
        if not reservation or reservation.reserved_usd == Decimal("0"):
            return

        reserved_usd = reservation.reserved_usd
        reserved_tokens = reservation.reserved_tokens

        # Release hold on account
        await self._account_repo.apply_release(user_id=user_id, reserved_usd=reserved_usd)

        # Mark reservation terminal
        await self._reservation_repo.mark_released(blog_session_id)

        # Ledger audit entry
        await self._budget_repo.write_entry(
            user_id=user_id,
            blog_session_id=blog_session_id,
            agent_run_id=None,
            entry_type=BudgetEntryType.RELEASE,
            tokens=reserved_tokens,
            amount_usd=reserved_usd,
            note="Full budget release on failure/cancellation",
        )

    # ------------------------------------------------------------------
    # Grant (on registration or admin top-up)
    # ------------------------------------------------------------------

    async def grant(
        self,
        *,
        user_id: int,
        tokens: int,
        amount_usd: Decimal,
        note: Optional[str] = None,
    ) -> None:
        """Grant budget to a user — updates account row and writes ledger entry."""
        await self._account_repo.apply_grant(user_id=user_id, amount_usd=amount_usd)
        await self._budget_repo.write_entry(
            user_id=user_id,
            blog_session_id=None,
            agent_run_id=None,
            entry_type=BudgetEntryType.GRANT,
            tokens=tokens,
            amount_usd=amount_usd,
            note=note or "Budget grant",
        )

    # ------------------------------------------------------------------
    # Balance snapshot (O(1) read from budget_accounts)
    # ------------------------------------------------------------------

    async def get_balance_snapshot(self, user_id: int) -> dict:
        snapshot = await self._account_repo.get_snapshot(user_id)
        return {
            "balance_usd": float(snapshot["balance_usd"]),
            "available_usd": float(snapshot["available_usd"]),
            "reserved_usd": float(snapshot["reserved_usd"]),
            "balance_tokens": int(snapshot["available_usd"] / Decimal("0.00002")),
        }