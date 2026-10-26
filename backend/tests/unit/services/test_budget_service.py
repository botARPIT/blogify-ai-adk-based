from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.models.orm_models import BudgetEntryType
from src.services.budget_service import BudgetService


def _build_service(
    *,
    reservation: SimpleNamespace | None,
    blog_session: SimpleNamespace | None,
) -> tuple[BudgetService, AsyncMock, AsyncMock, AsyncMock, AsyncMock]:
    budget_repo = AsyncMock()
    session_repo = AsyncMock()
    account_repo = AsyncMock()
    reservation_repo = AsyncMock()
    reservation_repo.get_by_session.return_value = reservation
    session_repo.get_by_id.return_value = blog_session
    budget_repo.get_committed_for_session.return_value = -(blog_session.budget_spent_usd if blog_session else Decimal("0"))
    budget_repo.get_committed_tokens_for_session.return_value = -(blog_session.budget_spent_tokens if blog_session else 0)

    service = BudgetService(
        budget_repo=budget_repo,
        session_repo=session_repo,
        account_repo=account_repo,
        reservation_repo=reservation_repo,
    )
    return service, budget_repo, session_repo, account_repo, reservation_repo


@pytest.mark.asyncio
async def test_release_excess_records_unused_tokens_and_usd() -> None:
    reservation = SimpleNamespace(
        reserved_tokens=50_000,
        reserved_usd=Decimal("1.00"),
    )
    blog_session = SimpleNamespace(
        budget_spent_tokens=12_000,
        budget_spent_usd=Decimal("0.24"),
    )
    service, budget_repo, _, account_repo, reservation_repo = _build_service(
        reservation=reservation,
        blog_session=blog_session,
    )

    # Deliberately stale session totals must not erase ledger charges.
    blog_session.budget_spent_usd = Decimal("0")
    blog_session.budget_spent_tokens = 0
    await service.release_excess(user_id=7, blog_session_id=41)

    account_repo.apply_commit.assert_awaited_once_with(
        user_id=7,
        reserved_usd=Decimal("1.00"),
        actual_usd=Decimal("0.24"),
    )
    reservation_repo.mark_committed.assert_awaited_once_with(41)
    budget_repo.write_entry.assert_awaited_once_with(
        user_id=7,
        blog_session_id=41,
        agent_run_id=None,
        entry_type=BudgetEntryType.RELEASE,
        tokens=38_000,
        amount_usd=Decimal("0.76"),
        note="Excess budget released after terminal workflow outcome",
    )


@pytest.mark.asyncio
async def test_release_excess_clamps_overages_to_zero() -> None:
    reservation = SimpleNamespace(
        reserved_tokens=50_000,
        reserved_usd=Decimal("1.00"),
    )
    blog_session = SimpleNamespace(
        budget_spent_tokens=55_000,
        budget_spent_usd=Decimal("1.10"),
    )
    service, budget_repo, _, _, _ = _build_service(
        reservation=reservation,
        blog_session=blog_session,
    )

    await service.release_excess(user_id=7, blog_session_id=41)

    release = budget_repo.write_entry.await_args.kwargs
    assert release["tokens"] == 0
    assert release["amount_usd"] == Decimal("0")


@pytest.mark.asyncio
async def test_release_excess_without_reservation_is_a_noop() -> None:
    service, budget_repo, session_repo, account_repo, reservation_repo = _build_service(
        reservation=None,
        blog_session=None,
    )

    await service.release_excess(user_id=7, blog_session_id=41)

    reservation_repo.get_by_session.assert_awaited_once_with(41)
    session_repo.get_by_id.assert_not_awaited()
    account_repo.apply_commit.assert_not_awaited()
    reservation_repo.mark_committed.assert_not_awaited()
    budget_repo.write_entry.assert_not_awaited()
