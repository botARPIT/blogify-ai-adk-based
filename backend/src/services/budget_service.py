"""BudgetService — enforces preflight checks and coordinates reserve/commit/release."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from src.models.orm_models import LedgerEntryType, LedgerResourceType
from src.models.repositories.budget_repository import BudgetRepository
from src.models.repositories.blog_session_repository import BlogSessionRepository
from src.models.schemas import BudgetDecision, BudgetSnapshot


# Estimated token usage per stage — tunable via config
STAGE_ESTIMATED_TOKENS: dict[str, int] = {
    "intent": 500,
    "outline": 2_000,
    "research": 1_000,
    "writer": 6_000,
    "editor": 3_000,
    "revision_writer": 6_000,
    "revision_editor": 3_000,
}

# Estimated cost per token in USD (rough average for gemini-2.5-flash-lite)
ESTIMATED_USD_PER_TOKEN = 0.000_003


def _estimate_session_usd(stages: list[str]) -> tuple[float, int]:
    total_tokens = sum(STAGE_ESTIMATED_TOKENS.get(s, 2_000) for s in stages)
    total_usd = total_tokens * ESTIMATED_USD_PER_TOKEN
    return round(total_usd, 6), total_tokens


class BudgetService:
    """Coordinates budget enforcement across the request lifecycle.

    Usage pattern:
        decision = await budget_svc.preflight(tenant_id, end_user_id)
        if not decision.allowed:
            raise BudgetExhaustedError(decision.reason)

        await budget_svc.reserve(tenant_id, end_user_id, session_id, decision)

        # after each stage:
        await budget_svc.commit_stage(tenant_id, end_user_id, session_id, run_id, tokens, usd)

        # on failure/cancel:
        await budget_svc.release(tenant_id, end_user_id, session_id)
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
        if stages is None:
            stages = ["intent", "outline", "research", "writer", "editor"]

        policy = await self._budget_repo.get_effective_policy(tenant_id, end_user_id)
        if not policy:
            # No policy means no limits configured — allow with zero budget tracking
            estimated_usd, estimated_tokens = _estimate_session_usd(stages)
            return BudgetDecision(
                allowed=True,
                reserved_usd=estimated_usd,
                reserved_tokens=estimated_tokens,
            )

        today = datetime.now(timezone.utc)
        daily_usd = await self._budget_repo.get_daily_spent(
            end_user_id, LedgerResourceType.USD, today
        )
        daily_tokens = await self._budget_repo.get_daily_spent(
            end_user_id, LedgerResourceType.TOKENS, today
        )

        estimated_usd, estimated_tokens = _estimate_session_usd(stages)

        # Check daily USD limit
        if daily_usd + estimated_usd > policy.daily_cost_limit_usd:
            return BudgetDecision(
                allowed=False,
                reason=(
                    f"Daily USD budget exhausted: "
                    f"${daily_usd:.4f} spent of ${policy.daily_cost_limit_usd:.2f} limit"
                ),
                daily_remaining_usd=max(0, policy.daily_cost_limit_usd - daily_usd),
                daily_remaining_tokens=max(0, policy.daily_token_limit - daily_tokens),
            )

        # Check daily token limit
        if daily_tokens + estimated_tokens > policy.daily_token_limit:
            return BudgetDecision(
                allowed=False,
                reason=(
                    f"Daily token budget exhausted: "
                    f"{int(daily_tokens)} used of {policy.daily_token_limit} limit"
                ),
                daily_remaining_usd=max(0, policy.daily_cost_limit_usd - daily_usd),
                daily_remaining_tokens=max(0, policy.daily_token_limit - daily_tokens),
            )

        # Check per-session cost limit
        if estimated_usd > policy.per_session_cost_limit_usd:
            return BudgetDecision(
                allowed=False,
                reason=(
                    f"Session cost estimate ${estimated_usd:.4f} exceeds "
                    f"per-session limit ${policy.per_session_cost_limit_usd:.2f}"
                ),
            )

        return BudgetDecision(
            allowed=True,
            reserved_usd=estimated_usd,
            reserved_tokens=estimated_tokens,
            daily_remaining_usd=policy.daily_cost_limit_usd - daily_usd - estimated_usd,
            daily_remaining_tokens=policy.daily_token_limit - daily_tokens - estimated_tokens,
            session_remaining_usd=policy.per_session_cost_limit_usd - estimated_usd,
            session_remaining_tokens=policy.per_session_token_limit - estimated_tokens,
        )

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
        reserved_usd: float,
        reserved_tokens: int,
        already_spent_usd: float = 0.0,
        already_spent_tokens: int = 0,
    ) -> None:
        """Release unused reserved budget on failure or cancellation."""
        release_usd = max(0.0, reserved_usd - already_spent_usd)
        release_tokens = max(0, reserved_tokens - already_spent_tokens)
        await self._budget_repo.release(
            tenant_id=tenant_id,
            end_user_id=end_user_id,
            blog_session_id=blog_session_id,
            release_usd=release_usd,
            release_tokens=release_tokens,
        )

    async def get_snapshot(
        self,
        tenant_id: int,
        end_user_id: int,
    ) -> BudgetSnapshot:
        """Return a point-in-time budget snapshot."""
        policy = await self._budget_repo.get_effective_policy(tenant_id, end_user_id)
        today = datetime.now(timezone.utc)
        daily_spent_usd = await self._budget_repo.get_daily_spent(
            end_user_id, LedgerResourceType.USD, today
        )
        daily_spent_tokens = await self._budget_repo.get_daily_spent(
            end_user_id, LedgerResourceType.TOKENS, today
        )
        return BudgetSnapshot(
            end_user_id=end_user_id,
            tenant_id=tenant_id,
            daily_spent_usd=daily_spent_usd,
            daily_spent_tokens=int(daily_spent_tokens),
            daily_limit_usd=policy.daily_cost_limit_usd if policy else 0.0,
            daily_limit_tokens=policy.daily_token_limit if policy else 0,
            active_sessions=0,  # TODO: query active sessions count
            max_concurrent_sessions=policy.max_concurrent_sessions if policy else 0,
            remaining_revision_iterations=(
                policy.max_revision_iterations_per_session if policy else 0
            ),
        )
