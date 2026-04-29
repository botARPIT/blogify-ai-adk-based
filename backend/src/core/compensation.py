"""Saga compensation — failure-aware budget handling for session termination.

Two failure categories drive different compensation strategies:

- **Operational** (user_cancelled, budget_exhausted):
    Commit whatever budget was consumed → release the remainder.
    The user triggered the stop, so they own the cost of work already done.

- **System** (agent_error, agent_timeout, dependency_error, worker_crash,
              max_retries_exceeded):
    Release the entire reservation.
    The system failed the user, so no cost is charged.
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

from src.config.logging_config import get_logger

if TYPE_CHECKING:
    from src.services.budget_service import BudgetService

logger = get_logger(__name__)


class FailureCategory(str, Enum):
    """Classifies why a session failed so compensation can decide what to do."""

    OPERATIONAL = "operational"  # user initiated or budget-driven
    SYSTEM = "system"           # infrastructure / agent / dependency


# ── failure_reason → category mapping ──────────────────────────────────
FAILURE_REASON_CATEGORIES: dict[str, FailureCategory] = {
    # Operational — user's cost
    "user_cancelled": FailureCategory.OPERATIONAL,
    "budget_exhausted": FailureCategory.OPERATIONAL,
    # System — platform's cost
    "agent_timeout": FailureCategory.SYSTEM,
    "agent_error": FailureCategory.SYSTEM,
    "dependency_error": FailureCategory.SYSTEM,
    "worker_crash": FailureCategory.SYSTEM,
    "max_retries_exceeded": FailureCategory.SYSTEM,
}


def classify_failure(failure_reason: str) -> FailureCategory:
    """Determine the failure category from a reason string.

    Unknown reasons default to SYSTEM (err on the side of not charging the user).
    """
    return FAILURE_REASON_CATEGORIES.get(failure_reason, FailureCategory.SYSTEM)


async def compensate(
    *,
    budget_service: BudgetService,
    tenant_id: int,
    end_user_id: int,
    session_id: int,
    failure_reason: str,
    service_client_id: int | None = None,
) -> None:
    """Execute compensation for a failed or cancelled session.

    Parameters
    ----------
    budget_service:
        The budget service instance (injected to avoid circular imports).
    tenant_id, end_user_id, session_id:
        Identity triple for the session being compensated.
    failure_reason:
        The reason string (e.g. ``"user_cancelled"``, ``"agent_error"``).
    service_client_id:
        Optional, forwarded to budget release if provided.
    """
    category = classify_failure(failure_reason)

    logger.info(
        "compensation_executing",
        session_id=session_id,
        failure_reason=failure_reason,
        category=category.value,
    )

    if category == FailureCategory.OPERATIONAL:
        # Commit consumed budget, release the remainder.
        # The `release()` method already calculates remainder by subtracting
        # spent amounts from the reservation when reserved_usd/tokens are None.
        await budget_service.release(
            tenant_id=tenant_id,
            end_user_id=end_user_id,
            blog_session_id=session_id,
            service_client_id=service_client_id,
            reason=failure_reason,
        )
    else:
        # System failure — release entire reservation (no cost to user).
        await budget_service.release(
            tenant_id=tenant_id,
            end_user_id=end_user_id,
            blog_session_id=session_id,
            service_client_id=service_client_id,
            reason=failure_reason,
        )

    logger.info(
        "compensation_completed",
        session_id=session_id,
        category=category.value,
    )
