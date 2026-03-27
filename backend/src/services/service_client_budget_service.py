"""Service-client-wide daily budget preflight and reporting."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.models.orm_models import ServiceClientBudgetPolicy
from src.models.repositories.service_client_budget_repository import (
    ServiceClientBudgetRepository,
)
from src.models.schemas import ServiceClientBudgetDecision, ServiceClientBudgetView


class ServiceClientBudgetService:
    """Evaluate and expose temporary service-client-wide daily lockout state."""

    def __init__(self, budget_repo: ServiceClientBudgetRepository) -> None:
        self._budget_repo = budget_repo

    @staticmethod
    def next_reset_at(now: datetime | None = None) -> datetime:
        current = now or datetime.now(timezone.utc)
        start_of_day = current.replace(hour=0, minute=0, second=0, microsecond=0)
        return start_of_day + timedelta(days=1)

    async def update_policy(
        self, service_client_id: int, daily_budget_limit_usd: float
    ) -> ServiceClientBudgetPolicy:
        return await self._budget_repo.upsert_policy(
            service_client_id=service_client_id,
            daily_budget_limit_usd=daily_budget_limit_usd,
        )

    async def get_state(self, service_client_id: int) -> ServiceClientBudgetView:
        now = datetime.now(timezone.utc)
        policy = await self._budget_repo.get_policy(service_client_id)
        daily_spent_usd = await self._budget_repo.get_daily_spent_usd(service_client_id, now)
        daily_limit_usd = 0.0
        currently_exhausted = False

        if policy is not None and policy.is_active and policy.daily_budget_limit_usd > 0:
            daily_limit_usd = policy.daily_budget_limit_usd
            currently_exhausted = daily_spent_usd >= daily_limit_usd

        return ServiceClientBudgetView(
            daily_budget_limit_usd=daily_limit_usd,
            budget_window="daily",
            currently_exhausted=currently_exhausted,
            reset_at=self.next_reset_at(now) if daily_limit_usd > 0 else None,
            daily_spent_usd=daily_spent_usd,
        )

    async def preflight(self, service_client_id: int) -> ServiceClientBudgetDecision:
        state = await self.get_state(service_client_id)
        if state.daily_budget_limit_usd <= 0:
            return ServiceClientBudgetDecision(
                allowed=True,
                daily_spent_usd=state.daily_spent_usd,
                daily_limit_usd=state.daily_budget_limit_usd,
                reset_at=state.reset_at,
            )
        if state.currently_exhausted:
            return ServiceClientBudgetDecision(
                allowed=False,
                reason=(
                    f"Service client's daily AI budget is exhausted: "
                    f"${state.daily_spent_usd:.4f} spent of ${state.daily_budget_limit_usd:.2f} limit"
                ),
                daily_spent_usd=state.daily_spent_usd,
                daily_limit_usd=state.daily_budget_limit_usd,
                reset_at=state.reset_at,
            )
        return ServiceClientBudgetDecision(
            allowed=True,
            daily_spent_usd=state.daily_spent_usd,
            daily_limit_usd=state.daily_budget_limit_usd,
            reset_at=state.reset_at,
        )
