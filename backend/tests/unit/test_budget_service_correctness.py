from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.services.budget_service import BudgetService


def _policy(**overrides):
    defaults = {
        "id": 1,
        "scope": "default",
        "daily_cost_limit_usd": 5.0,
        "daily_token_limit": 50_000,
        "daily_blog_limit": 5,
        "per_session_cost_limit_usd": 0.10,
        "per_session_token_limit": 15_000,
        "max_revision_iterations_per_session": 3,
        "max_concurrent_sessions": 2,
        "soft_stop_enabled": False,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _budget_repo(*, committed=None, reserved=None, policy=None):
    repo = AsyncMock()
    repo.get_effective_policy.return_value = policy or _policy()
    repo.get_daily_committed.side_effect = committed or [0.0, 0.0, 0.0]
    repo.get_daily_reserved_exposure.side_effect = reserved or [0.0, 0.0, 0.0]
    return repo


@pytest.mark.asyncio
async def test_generation_reservation_writes_ledger_entries():
    budget_repo = _budget_repo()
    session_repo = AsyncMock()

    context = await BudgetService(budget_repo, session_repo).reserve_generation_budget(
        tenant_id=5,
        end_user_id=11,
        service_client_id=9,
        blog_session_id=101,
        current_active_sessions_override=0,
    )

    assert context.decision.allowed is True
    budget_repo.reserve.assert_awaited_once()
    assert budget_repo.reserve.await_args.kwargs["reserve_blog_count"] is True
    assert budget_repo.reserve.await_args.kwargs["blog_session_id"] == 101


@pytest.mark.asyncio
async def test_generation_reservation_denies_when_concurrency_exhausted():
    budget_repo = _budget_repo(policy=_policy(max_concurrent_sessions=2))
    session_repo = AsyncMock()

    context = await BudgetService(budget_repo, session_repo).reserve_generation_budget(
        tenant_id=5,
        end_user_id=11,
        service_client_id=9,
        blog_session_id=101,
        current_active_sessions_override=2,
    )

    assert context.decision.allowed is False
    assert "Concurrent session budget exhausted" in context.decision.reason
    budget_repo.reserve.assert_not_awaited()


@pytest.mark.asyncio
async def test_snapshot_separates_committed_reserved_and_total_exposure():
    budget_repo = _budget_repo(
        committed=[1.25, 1200, 1],
        reserved=[0.75, 3000, 2],
    )
    session_repo = AsyncMock()
    session_repo.count_active_for_end_user.return_value = 2

    snapshot = await BudgetService(budget_repo, session_repo).get_snapshot(
        tenant_id=5,
        end_user_id=11,
    )

    assert snapshot.daily_spent_usd == 1.25
    assert snapshot.daily_committed_spend_usd == 1.25
    assert snapshot.daily_reserved_exposure_usd == 0.75
    assert snapshot.daily_total_exposure_usd == 2.0
    assert snapshot.daily_blog_count_committed == 1
    assert snapshot.daily_blog_count_reserved == 2


@pytest.mark.asyncio
async def test_release_after_queue_failure_releases_outstanding_exposure_and_blog_count():
    budget_repo = _budget_repo()
    budget_repo.get_session_reserved_exposure.side_effect = [0.0375, 12500]
    session_repo = AsyncMock()

    await BudgetService(budget_repo, session_repo).release(
        tenant_id=5,
        end_user_id=11,
        service_client_id=9,
        blog_session_id=101,
        reason="queue_failed",
    )

    budget_repo.release.assert_awaited_once_with(
        tenant_id=5,
        end_user_id=11,
        blog_session_id=101,
        release_usd=0.0375,
        release_tokens=12500,
        release_blog_count=True,
    )
