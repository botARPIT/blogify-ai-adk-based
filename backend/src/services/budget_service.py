"""BudgetService — DB-authoritative budget reservation and reporting."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from src.models.orm_models import BlogSessionStatus, LedgerResourceType
from src.models.repositories.budget_repository import BudgetRepository
from src.models.repositories.blog_session_repository import BlogSessionRepository
from src.models.schemas import BudgetDecision, BudgetSnapshot


# Estimated token usage per stage — tunable via config.
STAGE_ESTIMATED_TOKENS: dict[str, int] = {
    "intent": 500,
    "outline": 2_000,
    "research": 1_000,
    "writer": 6_000,
    "editor": 3_000,
    "revision_writer": 6_000,
    "revision_editor": 3_000,
}

# Estimated cost per token in USD (rough average for gemini-2.5-flash-lite).
ESTIMATED_USD_PER_TOKEN = 0.000_003
GENERATION_STAGES = ["intent", "outline", "research", "writer", "editor"]
REVISION_STAGES = ["revision_writer", "revision_editor"]


@dataclass(slots=True)
class BudgetReservationContext:
    """Result wrapper used by canonical routes."""

    decision: BudgetDecision


def _estimate_session_usd(stages: list[str]) -> tuple[float, int]:
    total_tokens = sum(STAGE_ESTIMATED_TOKENS.get(s, 2_000) for s in stages)
    total_usd = total_tokens * ESTIMATED_USD_PER_TOKEN
    return round(total_usd, 6), total_tokens


class BudgetService:
    """Coordinates budget enforcement across the request lifecycle.

    PostgreSQL ledger entries are the source of truth for all budget state.
    Redis queue/task data is transport-only and must not be used to decide
    budget availability or user-visible spend.
    """

    def __init__(
        self,
        budget_repo: BudgetRepository,
        session_repo: BlogSessionRepository,
    ) -> None:
        self._budget_repo = budget_repo
        self._session_repo = session_repo

    async def preflight(
        self,
        tenant_id: int,
        end_user_id: int,
        stages: Optional[list[str]] = None,
    ) -> BudgetDecision:
        """Check whether a new generation request can be allowed."""
        context = await self._build_decision(
            tenant_id=tenant_id,
            end_user_id=end_user_id,
            stages=stages or GENERATION_STAGES,
            reserves_blog_count=True,
        )
        return context.decision

    async def reserve_generation_budget(
        self,
        *,
        tenant_id: int,
        end_user_id: int,
        service_client_id: int | None = None,
        blog_session_id: int,
        current_active_sessions_override: int | None = None,
    ) -> BudgetReservationContext:
        context = await self._build_decision(
            tenant_id=tenant_id,
            end_user_id=end_user_id,
            stages=GENERATION_STAGES,
            reserves_blog_count=True,
            current_active_sessions_override=current_active_sessions_override,
        )
        if context.decision.allowed:
            await self._budget_repo.reserve(
                tenant_id=tenant_id,
                end_user_id=end_user_id,
                blog_session_id=blog_session_id,
                estimated_usd=context.decision.reserved_usd,
                estimated_tokens=context.decision.reserved_tokens,
                reserve_blog_count=True,
            )
        return context

    async def reserve_revision_budget(
        self,
        *,
        tenant_id: int,
        end_user_id: int,
        service_client_id: int | None = None,
        blog_session_id: int,
        iteration_number: int,
        current_session_spent_usd: float,
        current_session_spent_tokens: int,
    ) -> BudgetReservationContext:
        policy = await self._budget_repo.get_effective_policy(tenant_id, end_user_id)
        if policy and iteration_number > policy.max_revision_iterations_per_session:
            return BudgetReservationContext(
                BudgetDecision(
                    allowed=False,
                    reason=(
                        "Revision budget exhausted: "
                        f"{iteration_number}/{policy.max_revision_iterations_per_session} iterations used"
                    ),
                    error_code="BUDGET_EXCEEDED",
                    effective_policy_id=policy.id,
                    remaining_active_session_slots=0,
                )
            )

        context = await self._build_decision(
            tenant_id=tenant_id,
            end_user_id=end_user_id,
            stages=REVISION_STAGES,
            reserves_blog_count=False,
            current_session_spent_usd=current_session_spent_usd,
            current_session_spent_tokens=current_session_spent_tokens,
        )
        if context.decision.allowed:
            await self._budget_repo.reserve(
                tenant_id=tenant_id,
                end_user_id=end_user_id,
                blog_session_id=blog_session_id,
                estimated_usd=context.decision.reserved_usd,
                estimated_tokens=context.decision.reserved_tokens,
                reserve_blog_count=False,
            )
        return context

    async def reserve(
        self,
        tenant_id: int,
        end_user_id: int,
        blog_session_id: int,
        decision: BudgetDecision,
    ) -> None:
        """Reserve budget after a successful preflight check."""
        await self._budget_repo.reserve(
            tenant_id=tenant_id,
            end_user_id=end_user_id,
            blog_session_id=blog_session_id,
            estimated_usd=decision.reserved_usd,
            estimated_tokens=decision.reserved_tokens,
            reserve_blog_count=False,
        )

    async def commit_stage(
        self,
        tenant_id: int,
        end_user_id: int,
        blog_session_id: int,
        agent_run_id: int,
        actual_tokens: int,
        actual_usd: float,
    ) -> None:
        """Commit actual usage after a stage completes."""
        await self._budget_repo.commit(
            tenant_id=tenant_id,
            end_user_id=end_user_id,
            blog_session_id=blog_session_id,
            actual_usd=actual_usd,
            actual_tokens=actual_tokens,
            agent_run_id=agent_run_id,
        )
        await self._session_repo.commit_spend(
            blog_session_id, actual_usd, actual_tokens
        )

    async def release(
        self,
        tenant_id: int,
        end_user_id: int,
        blog_session_id: int,
        reserved_usd: float | None = None,
        reserved_tokens: int | None = None,
        already_spent_usd: float = 0.0,
        already_spent_tokens: int = 0,
        service_client_id: int | None = None,
        reason: str | None = None,
    ) -> None:
        """Release unused reserved budget on failure, cancellation, or queue rejection."""
        if reserved_usd is None:
            release_usd = await self._budget_repo.get_session_reserved_exposure(
                blog_session_id, LedgerResourceType.USD
            )
        else:
            release_usd = max(0.0, reserved_usd - already_spent_usd)

        if reserved_tokens is None:
            release_tokens = int(
                await self._budget_repo.get_session_reserved_exposure(
                    blog_session_id, LedgerResourceType.TOKENS
                )
            )
        else:
            release_tokens = max(0, reserved_tokens - already_spent_tokens)

        release_blog_count = await self._should_release_blog_count(blog_session_id, reason)
        await self._budget_repo.release(
            tenant_id=tenant_id,
            end_user_id=end_user_id,
            blog_session_id=blog_session_id,
            release_usd=release_usd,
            release_tokens=release_tokens,
            release_blog_count=release_blog_count,
        )

    async def get_snapshot(
        self,
        tenant_id: int,
        end_user_id: int,
    ) -> BudgetSnapshot:
        """Return a point-in-time budget snapshot."""
        policy = await self._budget_repo.get_effective_policy(tenant_id, end_user_id)
        today = datetime.now(timezone.utc)
        committed_usd = await self._budget_repo.get_daily_committed(
            end_user_id, LedgerResourceType.USD, today
        )
        committed_tokens = await self._budget_repo.get_daily_committed(
            end_user_id, LedgerResourceType.TOKENS, today
        )
        reserved_usd = await self._budget_repo.get_daily_reserved_exposure(
            end_user_id, LedgerResourceType.USD, today
        )
        reserved_tokens = await self._budget_repo.get_daily_reserved_exposure(
            end_user_id, LedgerResourceType.TOKENS, today
        )
        committed_blog_count = await self._budget_repo.get_daily_committed(
            end_user_id, LedgerResourceType.BLOG_COUNT, today
        )
        reserved_blog_count = await self._budget_repo.get_daily_reserved_exposure(
            end_user_id, LedgerResourceType.BLOG_COUNT, today
        )
        active_sessions = await self._session_repo.count_active_for_end_user(end_user_id)

        max_concurrent_sessions = policy.max_concurrent_sessions if policy else 0
        remaining_active_slots = (
            max(max_concurrent_sessions - active_sessions, 0)
            if max_concurrent_sessions > 0
            else 0
        )

        return BudgetSnapshot(
            end_user_id=end_user_id,
            tenant_id=tenant_id,
            policy_id=policy.id if policy else None,
            policy_scope=policy.scope if policy else None,
            daily_spent_usd=committed_usd,
            daily_spent_tokens=int(committed_tokens),
            daily_committed_spend_usd=committed_usd,
            daily_committed_tokens=int(committed_tokens),
            daily_reserved_exposure_usd=reserved_usd,
            daily_reserved_exposure_tokens=int(reserved_tokens),
            daily_total_exposure_usd=committed_usd + reserved_usd,
            daily_total_exposure_tokens=int(committed_tokens + reserved_tokens),
            daily_limit_usd=policy.daily_cost_limit_usd if policy else 0.0,
            daily_limit_tokens=policy.daily_token_limit if policy else 0,
            daily_blog_limit=policy.daily_blog_limit if policy else 0,
            daily_blog_count_committed=int(committed_blog_count),
            daily_blog_count_reserved=int(reserved_blog_count),
            active_sessions=active_sessions,
            max_concurrent_sessions=max_concurrent_sessions,
            remaining_revision_iterations=(
                policy.max_revision_iterations_per_session if policy else 0
            ),
            soft_stop_enabled=policy.soft_stop_enabled if policy else False,
        )

    async def _build_decision(
        self,
        *,
        tenant_id: int,
        end_user_id: int,
        stages: list[str],
        reserves_blog_count: bool,
        current_active_sessions_override: int | None = None,
        current_session_spent_usd: float = 0.0,
        current_session_spent_tokens: int = 0,
    ) -> BudgetReservationContext:
        policy = await self._budget_repo.get_effective_policy(tenant_id, end_user_id)
        estimated_usd, estimated_tokens = _estimate_session_usd(stages)
        if not policy:
            return BudgetReservationContext(
                BudgetDecision(
                    allowed=True,
                    estimated_usd=estimated_usd,
                    estimated_tokens=estimated_tokens,
                    reserved_usd=estimated_usd,
                    reserved_tokens=estimated_tokens,
                )
            )

        today = datetime.now(timezone.utc)
        committed_usd = await self._budget_repo.get_daily_committed(
            end_user_id, LedgerResourceType.USD, today
        )
        committed_tokens = await self._budget_repo.get_daily_committed(
            end_user_id, LedgerResourceType.TOKENS, today
        )
        reserved_usd = await self._budget_repo.get_daily_reserved_exposure(
            end_user_id, LedgerResourceType.USD, today
        )
        reserved_tokens = await self._budget_repo.get_daily_reserved_exposure(
            end_user_id, LedgerResourceType.TOKENS, today
        )
        committed_blog_count = await self._budget_repo.get_daily_committed(
            end_user_id, LedgerResourceType.BLOG_COUNT, today
        )
        reserved_blog_count = await self._budget_repo.get_daily_reserved_exposure(
            end_user_id, LedgerResourceType.BLOG_COUNT, today
        )
        active_sessions = (
            current_active_sessions_override
            if current_active_sessions_override is not None
            else await self._session_repo.count_active_for_end_user(end_user_id)
        )

        current_usd_exposure = committed_usd + reserved_usd
        current_token_exposure = committed_tokens + reserved_tokens
        current_blog_exposure = committed_blog_count + reserved_blog_count
        remaining_slots = max(policy.max_concurrent_sessions - active_sessions, 0)

        if reserves_blog_count and active_sessions >= policy.max_concurrent_sessions:
            return self._denied(
                policy_id=policy.id,
                reason=(
                    "Concurrent session budget exhausted: "
                    f"{active_sessions}/{policy.max_concurrent_sessions} active sessions"
                ),
                daily_remaining_usd=policy.daily_cost_limit_usd - current_usd_exposure,
                daily_remaining_tokens=policy.daily_token_limit - current_token_exposure,
                daily_remaining_blog_count=policy.daily_blog_limit - current_blog_exposure,
                remaining_active_session_slots=remaining_slots,
            )

        if current_usd_exposure + estimated_usd > policy.daily_cost_limit_usd:
            return self._denied(
                policy_id=policy.id,
                reason=(
                    "Daily USD budget exhausted: "
                    f"${current_usd_exposure:.4f} exposed of "
                    f"${policy.daily_cost_limit_usd:.2f} limit"
                ),
                daily_remaining_usd=policy.daily_cost_limit_usd - current_usd_exposure,
                daily_remaining_tokens=policy.daily_token_limit - current_token_exposure,
                daily_remaining_blog_count=policy.daily_blog_limit - current_blog_exposure,
                remaining_active_session_slots=remaining_slots,
            )

        if current_token_exposure + estimated_tokens > policy.daily_token_limit:
            return self._denied(
                policy_id=policy.id,
                reason=(
                    "Daily token budget exhausted: "
                    f"{int(current_token_exposure)} exposed of {policy.daily_token_limit} limit"
                ),
                daily_remaining_usd=policy.daily_cost_limit_usd - current_usd_exposure,
                daily_remaining_tokens=policy.daily_token_limit - current_token_exposure,
                daily_remaining_blog_count=policy.daily_blog_limit - current_blog_exposure,
                remaining_active_session_slots=remaining_slots,
            )

        if reserves_blog_count and current_blog_exposure + 1 > policy.daily_blog_limit:
            return self._denied(
                policy_id=policy.id,
                reason=(
                    "Daily blog budget exhausted: "
                    f"{int(current_blog_exposure)} exposed of {policy.daily_blog_limit} limit"
                ),
                daily_remaining_usd=policy.daily_cost_limit_usd - current_usd_exposure,
                daily_remaining_tokens=policy.daily_token_limit - current_token_exposure,
                daily_remaining_blog_count=policy.daily_blog_limit - current_blog_exposure,
                remaining_active_session_slots=remaining_slots,
            )

        if current_session_spent_usd + estimated_usd > policy.per_session_cost_limit_usd:
            return self._denied(
                policy_id=policy.id,
                reason=(
                    f"Session cost estimate ${current_session_spent_usd + estimated_usd:.4f} "
                    f"exceeds per-session limit ${policy.per_session_cost_limit_usd:.2f}"
                ),
                daily_remaining_usd=policy.daily_cost_limit_usd - current_usd_exposure,
                daily_remaining_tokens=policy.daily_token_limit - current_token_exposure,
                daily_remaining_blog_count=policy.daily_blog_limit - current_blog_exposure,
                remaining_active_session_slots=remaining_slots,
            )

        if current_session_spent_tokens + estimated_tokens > policy.per_session_token_limit:
            return self._denied(
                policy_id=policy.id,
                reason=(
                    f"Session token estimate {current_session_spent_tokens + estimated_tokens} "
                    f"exceeds per-session limit {policy.per_session_token_limit}"
                ),
                daily_remaining_usd=policy.daily_cost_limit_usd - current_usd_exposure,
                daily_remaining_tokens=policy.daily_token_limit - current_token_exposure,
                daily_remaining_blog_count=policy.daily_blog_limit - current_blog_exposure,
                remaining_active_session_slots=remaining_slots,
            )

        return BudgetReservationContext(
            BudgetDecision(
                allowed=True,
                effective_policy_id=policy.id,
                estimated_usd=estimated_usd,
                estimated_tokens=estimated_tokens,
                reserved_usd=estimated_usd,
                reserved_tokens=estimated_tokens,
                daily_remaining_usd=policy.daily_cost_limit_usd - current_usd_exposure - estimated_usd,
                daily_remaining_tokens=int(
                    policy.daily_token_limit - current_token_exposure - estimated_tokens
                ),
                session_remaining_usd=(
                    policy.per_session_cost_limit_usd
                    - current_session_spent_usd
                    - estimated_usd
                ),
                session_remaining_tokens=(
                    policy.per_session_token_limit
                    - current_session_spent_tokens
                    - estimated_tokens
                ),
                daily_remaining_blog_count=int(
                    policy.daily_blog_limit
                    - current_blog_exposure
                    - (1 if reserves_blog_count else 0)
                ),
                remaining_active_session_slots=(
                    max(remaining_slots - 1, 0) if reserves_blog_count else remaining_slots
                ),
                soft_stop_enabled=policy.soft_stop_enabled,
            )
        )

    def _denied(
        self,
        *,
        policy_id: int,
        reason: str,
        daily_remaining_usd: float,
        daily_remaining_tokens: float,
        daily_remaining_blog_count: float,
        remaining_active_session_slots: int,
    ) -> BudgetReservationContext:
        return BudgetReservationContext(
            BudgetDecision(
                allowed=False,
                reason=reason,
                error_code="BUDGET_EXCEEDED",
                effective_policy_id=policy_id,
                daily_remaining_usd=max(0.0, daily_remaining_usd),
                daily_remaining_tokens=max(0, int(daily_remaining_tokens)),
                daily_remaining_blog_count=max(0, int(daily_remaining_blog_count)),
                remaining_active_session_slots=max(0, remaining_active_session_slots),
            )
        )

    async def _should_release_blog_count(
        self,
        blog_session_id: int,
        reason: str | None,
    ) -> bool:
        if reason in {"queue_rejected", "queue_failed"}:
            return True

        blog_session = await self._session_repo.get_by_id(blog_session_id)
        if blog_session is None:
            return False
        return blog_session.status in {
            BlogSessionStatus.FAILED.value,
            BlogSessionStatus.CANCELLED.value,
            BlogSessionStatus.BUDGET_EXHAUSTED.value,
            BlogSessionStatus.FAILED,
            BlogSessionStatus.CANCELLED,
            BlogSessionStatus.BUDGET_EXHAUSTED,
        }
