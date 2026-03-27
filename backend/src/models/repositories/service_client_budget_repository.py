"""Service-client-wide budget policy and spend queries."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.orm_models import (
    BudgetLedgerEntry,
    LedgerEntryType,
    LedgerResourceType,
    ServiceClientBudgetPolicy,
    Tenant,
)


class ServiceClientBudgetRepository:
    """Read and update service-client budget policy and current spend."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_policy(self, service_client_id: int) -> ServiceClientBudgetPolicy | None:
        result = await self._session.execute(
            select(ServiceClientBudgetPolicy).where(
                ServiceClientBudgetPolicy.service_client_id == service_client_id
            )
        )
        return result.scalar_one_or_none()

    async def upsert_policy(
        self, service_client_id: int, daily_budget_limit_usd: float
    ) -> ServiceClientBudgetPolicy:
        policy = await self.get_policy(service_client_id)
        if policy is None:
            policy = ServiceClientBudgetPolicy(
                service_client_id=service_client_id,
                daily_budget_limit_usd=daily_budget_limit_usd,
                currency_code="USD",
                is_active=True,
            )
            self._session.add(policy)
        else:
            policy.daily_budget_limit_usd = daily_budget_limit_usd
            policy.currency_code = "USD"
            policy.is_active = True
        await self._session.flush()
        return policy

    async def get_daily_spent_usd(self, service_client_id: int, date_utc: datetime) -> float:
        start_of_day = date_utc.replace(hour=0, minute=0, second=0, microsecond=0)
        signed_quantity = case(
            (
                BudgetLedgerEntry.entry_type == LedgerEntryType.RELEASE.value,
                -BudgetLedgerEntry.quantity,
            ),
            else_=BudgetLedgerEntry.quantity,
        )
        result = await self._session.execute(
            select(func.coalesce(func.sum(signed_quantity), 0.0))
            .select_from(BudgetLedgerEntry)
            .join(Tenant, Tenant.id == BudgetLedgerEntry.tenant_id)
            .where(
                Tenant.service_client_id == service_client_id,
                BudgetLedgerEntry.resource_type == LedgerResourceType.USD.value,
                BudgetLedgerEntry.entry_type.in_(
                    [
                        LedgerEntryType.COMMIT.value,
                        LedgerEntryType.RESERVE.value,
                        LedgerEntryType.RELEASE.value,
                    ]
                ),
                BudgetLedgerEntry.created_at >= start_of_day,
            )
        )
        return float(result.scalar_one() or 0.0)
