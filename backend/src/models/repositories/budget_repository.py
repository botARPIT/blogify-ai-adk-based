"""BudgetRepository — reads policies and writes ledger entries."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.orm_models import (
    BlogSession,
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
        """Return total budget exposure for today.

        PostgreSQL is the authority for budget state. Exposure is committed
        usage plus outstanding reservations; Redis queue state is deliberately
        ignored here.
        """
        committed = await self.get_daily_committed(end_user_id, resource_type, date_utc)
        reserved = await self.get_daily_reserved_exposure(end_user_id, resource_type, date_utc)
        return committed + reserved

    async def get_daily_committed(
        self, end_user_id: int, resource_type: LedgerResourceType, date_utc: datetime
    ) -> float:
        """Return committed usage for the current UTC day."""
        start_of_day = date_utc.replace(hour=0, minute=0, second=0, microsecond=0)
        return await self._sum_entries(
            end_user_id=end_user_id,
            resource_type=resource_type,
            entry_type=LedgerEntryType.COMMIT,
            start_of_day=start_of_day,
        )

    async def get_daily_reserved_exposure(
        self, end_user_id: int, resource_type: LedgerResourceType, date_utc: datetime
    ) -> float:
        """Return outstanding reserved exposure for the current UTC day."""
        start_of_day = date_utc.replace(hour=0, minute=0, second=0, microsecond=0)
        reserved = case(
            (
                BudgetLedgerEntry.entry_type == LedgerEntryType.RESERVE.value,
                BudgetLedgerEntry.quantity,
            ),
            else_=0.0,
        )
        released = case(
            (
                BudgetLedgerEntry.entry_type == LedgerEntryType.RELEASE.value,
                BudgetLedgerEntry.quantity,
            ),
            else_=0.0,
        )
        committed = case(
            (
                BudgetLedgerEntry.entry_type == LedgerEntryType.COMMIT.value,
                BudgetLedgerEntry.quantity,
            ),
            else_=0.0,
        )
        per_session = (
            select(
                BudgetLedgerEntry.blog_session_id.label("blog_session_id"),
                (
                    func.coalesce(func.sum(reserved), 0.0)
                    - func.coalesce(func.sum(released), 0.0)
                    - func.coalesce(func.sum(committed), 0.0)
                ).label("outstanding"),
            )
            .where(
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
            .group_by(BudgetLedgerEntry.blog_session_id)
            .subquery()
        )
        result = await self._session.execute(
            select(func.coalesce(func.sum(func.greatest(per_session.c.outstanding, 0.0)), 0.0))
        )
        return float(result.scalar_one() or 0.0)

    async def get_session_reserved_exposure(
        self, blog_session_id: int, resource_type: LedgerResourceType
    ) -> float:
        """Return outstanding reservation for a session/resource."""
        reserved = await self._sum_session_entries(
            blog_session_id=blog_session_id,
            resource_type=resource_type,
            entry_type=LedgerEntryType.RESERVE,
        )
        released = await self._sum_session_entries(
            blog_session_id=blog_session_id,
            resource_type=resource_type,
            entry_type=LedgerEntryType.RELEASE,
        )
        committed = await self._sum_session_entries(
            blog_session_id=blog_session_id,
            resource_type=resource_type,
            entry_type=LedgerEntryType.COMMIT,
        )
        return max(0.0, reserved - released - committed)

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

    async def _sum_entries(
        self,
        *,
        end_user_id: int,
        resource_type: LedgerResourceType,
        entry_type: LedgerEntryType,
        start_of_day: datetime,
    ) -> float:
        result = await self._session.execute(
            select(func.coalesce(func.sum(BudgetLedgerEntry.quantity), 0.0)).where(
                BudgetLedgerEntry.end_user_id == end_user_id,
                BudgetLedgerEntry.resource_type == resource_type.value,
                BudgetLedgerEntry.entry_type == entry_type.value,
                BudgetLedgerEntry.created_at >= start_of_day,
            )
        )
        return float(result.scalar_one() or 0.0)

    async def _sum_session_entries(
        self,
        *,
        blog_session_id: int,
        resource_type: LedgerResourceType,
        entry_type: LedgerEntryType,
    ) -> float:
        result = await self._session.execute(
            select(func.coalesce(func.sum(BudgetLedgerEntry.quantity), 0.0)).where(
                BudgetLedgerEntry.blog_session_id == blog_session_id,
                BudgetLedgerEntry.resource_type == resource_type.value,
                BudgetLedgerEntry.entry_type == entry_type.value,
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
        reserve_blog_count: bool = False,
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
        if reserve_blog_count:
            await self.append_entry(
                tenant_id=tenant_id,
                end_user_id=end_user_id,
                entry_type=LedgerEntryType.RESERVE,
                resource_type=LedgerResourceType.BLOG_COUNT,
                quantity=1.0,
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
        release_blog_count: bool = False,
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
        if release_blog_count:
            outstanding_blog_count = await self.get_session_reserved_exposure(
                blog_session_id, LedgerResourceType.BLOG_COUNT
            )
            if outstanding_blog_count > 0:
                await self.append_entry(
                    tenant_id=tenant_id,
                    end_user_id=end_user_id,
                    entry_type=LedgerEntryType.RELEASE,
                    resource_type=LedgerResourceType.BLOG_COUNT,
                    quantity=outstanding_blog_count,
                    blog_session_id=blog_session_id,
                )

    async def release_reservation(self, blog_session_id: int) -> None:
        """Release all outstanding reservations for a permanently failed session."""
        blog_session = await self._session.get(BlogSession, blog_session_id)
        if blog_session is None:
            return
        release_usd = await self.get_session_reserved_exposure(
            blog_session_id, LedgerResourceType.USD
        )
        release_tokens = int(
            await self.get_session_reserved_exposure(
                blog_session_id, LedgerResourceType.TOKENS
            )
        )
        await self.release(
            tenant_id=blog_session.tenant_id,
            end_user_id=blog_session.end_user_id,
            blog_session_id=blog_session_id,
            release_usd=release_usd,
            release_tokens=release_tokens,
            release_blog_count=True,
        )
