"""BudgetRepository — reads policies and writes ledger entries."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.orm_models import (
    BudgetLedgerEntry,
    BudgetPolicy,
    BudgetPolicyScope,
    LedgerEntryType,
    LedgerResourceType,
)


class BudgetRepository:
    """Read budget policies and append-write ledger entries."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Policy resolution
    # ------------------------------------------------------------------

    async def get_effective_policy(
        self, tenant_id: int, end_user_id: int
    ) -> Optional[BudgetPolicy]:
        """Resolve effective policy in order: user_override → tenant → default."""
        # 1. user override
        result = await self._session.execute(
            select(BudgetPolicy).where(
                BudgetPolicy.end_user_id == end_user_id,
                BudgetPolicy.scope == BudgetPolicyScope.USER_OVERRIDE.value,
            )
        )
        policy = result.scalar_one_or_none()
        if policy:
            return policy

        # 2. tenant policy
        result = await self._session.execute(
            select(BudgetPolicy).where(
                BudgetPolicy.tenant_id == tenant_id,
                BudgetPolicy.scope == BudgetPolicyScope.TENANT.value,
            )
        )
        policy = result.scalar_one_or_none()
        if policy:
            return policy

        # 3. global default
        result = await self._session.execute(
            select(BudgetPolicy).where(
                BudgetPolicy.scope == BudgetPolicyScope.DEFAULT.value,
                BudgetPolicy.tenant_id.is_(None),
                BudgetPolicy.end_user_id.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def create_default_policy(self) -> BudgetPolicy:
        """Upsert the global default budget policy."""
        existing = await self._session.execute(
            select(BudgetPolicy).where(
                BudgetPolicy.scope == BudgetPolicyScope.DEFAULT.value,
                BudgetPolicy.tenant_id.is_(None),
                BudgetPolicy.end_user_id.is_(None),
            )
        )
        policy = existing.scalar_one_or_none()
        if policy:
            return policy
        policy = BudgetPolicy(scope=BudgetPolicyScope.DEFAULT.value)
        policy.scope = BudgetPolicyScope.DEFAULT
        self._session.add(policy)
        await self._session.flush()
        return policy

    # ------------------------------------------------------------------
    # Ledger queries
    # ------------------------------------------------------------------

    async def get_daily_spent(
        self, end_user_id: int, resource_type: LedgerResourceType, date_utc: datetime
    ) -> float:
        """Return net reserved and committed spend for today."""
        start_of_day = date_utc.replace(hour=0, minute=0, second=0, microsecond=0)
        signed_quantity = case(
            (
                BudgetLedgerEntry.entry_type == LedgerEntryType.RELEASE.value,
                -BudgetLedgerEntry.quantity,
            ),
            else_=BudgetLedgerEntry.quantity,
        )
        result = await self._session.execute(
            select(func.coalesce(func.sum(signed_quantity), 0.0)).where(
                BudgetLedgerEntry.end_user_id == end_user_id,
                BudgetLedgerEntry.resource_type == resource_type.value,
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

    async def get_session_spent(
        self, blog_session_id: int, resource_type: LedgerResourceType
    ) -> float:
        result = await self._session.execute(
            select(func.coalesce(func.sum(BudgetLedgerEntry.quantity), 0.0)).where(
                BudgetLedgerEntry.blog_session_id == blog_session_id,
                BudgetLedgerEntry.resource_type == resource_type.value,
                BudgetLedgerEntry.entry_type == LedgerEntryType.COMMIT.value,
            )
        )
        return float(result.scalar_one() or 0.0)

    # ------------------------------------------------------------------
    # Ledger writes (append-only)
    # ------------------------------------------------------------------

    async def append_entry(
        self,
        tenant_id: int,
        end_user_id: int,
        entry_type: LedgerEntryType,
        resource_type: LedgerResourceType,
        quantity: float,
        blog_session_id: Optional[int] = None,
        blog_version_id: Optional[int] = None,
        agent_run_id: Optional[int] = None,
        unit_cost_usd: Optional[float] = None,
        metadata: Optional[dict] = None,
    ) -> BudgetLedgerEntry:
        entry = BudgetLedgerEntry(
            tenant_id=tenant_id,
            end_user_id=end_user_id,
            blog_session_id=blog_session_id,
            blog_version_id=blog_version_id,
            agent_run_id=agent_run_id,
            entry_type=entry_type,
            resource_type=resource_type,
            quantity=quantity,
            unit_cost_usd=unit_cost_usd,
            metadata_=metadata,
        )
        self._session.add(entry)
        await self._session.flush()
        return entry

    async def reserve(
        self,
        tenant_id: int,
        end_user_id: int,
        blog_session_id: int,
        estimated_usd: float,
        estimated_tokens: int,
    ) -> None:
        """Reserve budget before starting generation."""
        await self.append_entry(
            tenant_id=tenant_id,
            end_user_id=end_user_id,
            entry_type=LedgerEntryType.RESERVE,
            resource_type=LedgerResourceType.USD,
            quantity=estimated_usd,
            blog_session_id=blog_session_id,
        )
        await self.append_entry(
            tenant_id=tenant_id,
            end_user_id=end_user_id,
            entry_type=LedgerEntryType.RESERVE,
            resource_type=LedgerResourceType.TOKENS,
            quantity=float(estimated_tokens),
            blog_session_id=blog_session_id,
        )

    async def commit(
        self,
        tenant_id: int,
        end_user_id: int,
        blog_session_id: int,
        actual_usd: float,
        actual_tokens: int,
        agent_run_id: Optional[int] = None,
    ) -> None:
        """Commit actual usage after stage completion."""
        await self.append_entry(
            tenant_id=tenant_id,
            end_user_id=end_user_id,
            entry_type=LedgerEntryType.COMMIT,
            resource_type=LedgerResourceType.USD,
            quantity=actual_usd,
            blog_session_id=blog_session_id,
            agent_run_id=agent_run_id,
        )
        await self.append_entry(
            tenant_id=tenant_id,
            end_user_id=end_user_id,
            entry_type=LedgerEntryType.COMMIT,
            resource_type=LedgerResourceType.TOKENS,
            quantity=float(actual_tokens),
            blog_session_id=blog_session_id,
            agent_run_id=agent_run_id,
        )

    async def release(
        self,
        tenant_id: int,
        end_user_id: int,
        blog_session_id: int,
        release_usd: float,
        release_tokens: int,
    ) -> None:
        """Release unused reserved budget after failure or cancellation."""
        if release_usd > 0:
            await self.append_entry(
                tenant_id=tenant_id,
                end_user_id=end_user_id,
                entry_type=LedgerEntryType.RELEASE,
                resource_type=LedgerResourceType.USD,
                quantity=release_usd,
                blog_session_id=blog_session_id,
            )
        if release_tokens > 0:
            await self.append_entry(
                tenant_id=tenant_id,
                end_user_id=end_user_id,
                entry_type=LedgerEntryType.RELEASE,
                resource_type=LedgerResourceType.TOKENS,
                quantity=float(release_tokens),
                blog_session_id=blog_session_id,
            )
