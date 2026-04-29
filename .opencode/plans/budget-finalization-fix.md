# Budget Finalization Two-Layer Fix

## Problem

`_finalize_canonical_success()` in `stage_executor.py` calls `check_stage_budget()` during post-execution finalization. This method is designed as a pre-flight check, not a post-execution validator. When the pipeline pauses for outline review, intent/outline costs are committed. On resume, `check_stage_budget()` subtracts only the current stage's estimate from `committed + reserved`, but `committed_usd` already includes the gate-committed costs. This causes false budget exhaustion.

Additionally, `canonical_costs_fallback_used` means actual token counts weren't captured — estimated values are committed to the ledger, which is an audit problem.

## Solution: Three Coordinated Changes

### Change 1: Replace `check_stage_budget()` with Two-Layer Validation

**Layer 1 — `assert_reservation_valid()`**: Verify reservation is still ACTIVE, lease not expired, user's daily cap not consumed by another pipeline.

**Layer 2 — `assert_within_reservation()`**: Verify actual total spend (already committed + new finalization cost) fits within original reservation + tolerance. Only check stages NOT already committed during the gate phase.

### Change 2: Tolerance + Instrumentation

`DEFAULT_FINALIZATION_TOLERANCE_USD = 0.005` — allows small floating-point/metering variance. Instrument overspend delta via Prometheus histogram for empirical tuning.

### Change 3: Fallback Cost Alerting

Flag fallback estimates in the ledger with `source="fallback_estimate"` and `requires_reconciliation=True`. Emit high-severity alert (not just a log warning).

---

## File Changes

### 1. NEW: `backend/src/services/budget_exceptions.py`

```python
"""Custom exceptions for budget enforcement during finalization."""

from __future__ import annotations


class BudgetError(Exception):
    """Base exception for budget-related failures."""


class BudgetExhausted(BudgetError):
    """Raised when actual costs exceed the reservation or daily cap."""


class BudgetReservationError(BudgetError):
    """Raised when a reservation is in an invalid state for finalization."""
```

### 2. MODIFY: `backend/src/models/repositories/budget_repository.py`

Add two methods near the end of the `BudgetRepository` class (after `mark_session_budget_exhausted`, before EOF):

```python
async def get_reservation_for_update(
    self,
    reservation_id: int,
) -> BudgetReservation | None:
    """Fetch a specific reservation with row-level lock."""
    stmt = select(BudgetReservation).where(
        BudgetReservation.id == reservation_id
    ).with_for_update()
    result = await self._session.execute(stmt)
    return result.scalar_one_or_none()

async def get_committed_cost_for_reservation(
    self,
    reservation_id: int,
) -> tuple[float, int]:
    """Return (committed_usd, committed_tokens) for a reservation."""
    stmt = select(
        BudgetReservation.committed_usd,
        BudgetReservation.committed_tokens,
    ).where(BudgetReservation.id == reservation_id)
    result = await self._session.execute(stmt)
    row = result.one_or_none()
    if row is None:
        return (0.0, 0)
    return (row[0], row[1])
```

### 3. MODIFY: `backend/src/services/budget_service.py`

#### 3a. Add imports at the top (after existing imports):

```python
from dataclasses import dataclass, field
from typing import Literal

from src.services.budget_exceptions import BudgetError, BudgetExhausted, BudgetReservationError
from src.monitoring import metrics
```

#### 3b. Add new dataclass and constants (after `DEFAULT_LEASE_MINUTES`):

```python
DEFAULT_FINALIZATION_TOLERANCE_USD = 0.005

GATE_COMMITTED_STAGES = frozenset({"intent", "outline"})


@dataclass(slots=True)
class CostRecord:
    """A stage cost with provenance tracking for audit and reconciliation."""
    stage: str
    amount_usd: float
    amount_tokens: int
    source: Literal["actual", "fallback_estimate"] = "actual"
    requires_reconciliation: bool = False
```

#### 3c. Add three new methods to `BudgetService` class (before `finalize_reservation` method):

```python
async def assert_reservation_valid(
    self,
    reservation_id: int,
) -> None:
    """
    Layer 1: Verify the reservation is still valid before touching anything.
    Raises BudgetReservationError if expired, already settled, or the user's
    daily cap has since been consumed by another pipeline.
    """
    reservation = await self._budget_repo.get_reservation_for_update(reservation_id)
    if reservation is None:
        raise BudgetReservationError(
            f"Reservation {reservation_id} not found. "
            f"Cannot finalize a pipeline against a missing reservation."
        )

    if reservation.status != BudgetReservationStatus.ACTIVE.value:
        raise BudgetReservationError(
            f"Reservation {reservation_id} is in state "
            f"'{reservation.status}', expected 'active'. "
            f"Cannot finalize a pipeline against an inactive reservation."
        )

    if reservation.lease_expires_at and reservation.lease_expires_at < datetime.now(timezone.utc):
        raise BudgetReservationError(
            f"Reservation {reservation_id} expired at {reservation.lease_expires_at}. "
            f"Credits may have been released and re-consumed."
        )

    policy = await self.ensure_effective_policy(reservation.tenant_id, reservation.end_user_id)
    state = await self._budget_repo.get_or_create_budget_state_for_update(
        reservation.tenant_id, reservation.end_user_id, policy
    )
    if state.committed_usd > state.daily_limit_usd:
        raise BudgetExhausted(
            f"User daily limit exceeded since reservation was created. "
            f"Committed: ${state.committed_usd:.4f}, Limit: ${state.daily_limit_usd:.2f}"
        )

async def assert_within_reservation(
    self,
    reservation_id: int,
    finalization_cost_usd: float,
    finalization_tokens: int,
    tolerance_usd: float = DEFAULT_FINALIZATION_TOLERANCE_USD,
) -> None:
    """
    Layer 2: Verify actual total spend fits within the reservation.
    Uses the original reserved amount, not the current remaining balance,
    because gate-committed stages already drew down from the same reservation.
    """
    reservation = await self._budget_repo.get_reservation_for_update(reservation_id)
    if reservation is None:
        raise BudgetReservationError(f"Reservation {reservation_id} not found")

    already_committed_usd, already_committed_tokens = (
        await self._budget_repo.get_committed_cost_for_reservation(reservation_id)
    )

    total_actual_usd = already_committed_usd + finalization_cost_usd
    total_actual_tokens = already_committed_tokens + finalization_tokens

    overspend_usd = total_actual_usd - reservation.reserved_usd
    overspend_tokens = total_actual_tokens - reservation.reserved_tokens

    metrics.budget_finalization_overspend_delta.observe(overspend_usd)

    if overspend_usd > tolerance_usd:
        raise BudgetExhausted(
            f"Pipeline actual cost (${total_actual_usd:.4f}) exceeds reservation "
            f"(${reservation.reserved_usd:.4f}) by ${overspend_usd:.4f}. "
            f"Overspend logged for review."
        )

    if overspend_tokens > 0:
        logger = __import__("src.config.logging_config", fromlist=["get_logger"]).get_logger(__name__)
        logger.warning(
            "budget_finalization_token_overspend",
            reservation_id=reservation_id,
            overspend_tokens=overspend_tokens,
        )

async def finalize_stage_costs(
    self,
    reservation_id: int,
    stage_costs: dict[str, CostRecord],
    *,
    tenant_id: int,
    end_user_id: int,
    service_client_id: int,
    blog_session_id: int,
) -> None:
    """Commit each stage cost to the ledger, flagging fallback records for reconciliation."""
    policy = await self.ensure_effective_policy(tenant_id, end_user_id)
    state = await self._budget_repo.get_or_create_budget_state_for_update(
        tenant_id, end_user_id, policy
    )
    reservation = await self._budget_repo.get_reservation_for_update(reservation_id)
    if reservation is None:
        raise BudgetReservationError(f"Reservation {reservation_id} not found")

    service_client_state = None
    service_client_policy = await self._budget_repo.get_service_client_policy(service_client_id)
    if (
        service_client_policy is not None
        and service_client_policy.is_active
        and service_client_policy.daily_budget_limit_usd > 0
    ):
        service_client_state = await self._budget_repo.get_or_create_service_client_state_for_update(
            service_client_id,
            service_client_policy.daily_budget_limit_usd,
        )

    for stage, cost in stage_costs.items():
        if cost.amount_tokens == 0:
            continue

        await self._budget_repo.apply_commit(
            state=state,
            reservation=reservation,
            actual_usd=cost.amount_usd,
            actual_tokens=cost.amount_tokens,
            blog_session_id=blog_session_id,
            tenant_id=tenant_id,
            end_user_id=end_user_id,
            agent_run_id=None,
            service_client_state=service_client_state,
        )

        if cost.source == "fallback_estimate" or cost.requires_reconciliation:
            metrics.budget_fallback_cost_total.labels(stage=stage).inc()

        await self._session_repo.commit_spend(
            blog_session_id, cost.amount_usd, cost.amount_tokens
        )

    await self._budget_repo.refresh_reservation_lease(
        reservation.id,
        self.reservation_lease(),
    )
```

### 4. MODIFY: `backend/src/workers/stage_executor.py`

#### 4a. Add imports at the top (after existing imports):

```python
from src.services.budget_exceptions import BudgetError, BudgetExhausted, BudgetReservationError
from src.services.budget_service import CostRecord, GATE_COMMITTED_STAGES
```

#### 4b. Replace `_canonical_costs_for_finalization` method:

Current method (lines 403-433) returns `list[CostInfo]`. Replace with:

```python
def _canonical_costs_for_finalization(
    self, result: PipelineResult
) -> list[CostRecord]:
    actual_by_stage = {
        cost.stage: cost for cost in result.costs if cost.total_tokens > 0
    }
    normalized: list[CostRecord] = []
    inferred_stages: list[str] = []

    for stage in STAGE_ORDER:
        if stage in ("intent", "outline"):
            continue
        if stage == "research" and not result.research:
            continue
        if stage == "writer" and not (result.draft or result.final_content):
            continue
        if stage == "editor" and not (result.editor_review or result.final_content):
            continue
        inferred_stages.append(stage)

    fallback_stages: list[str] = []
    for stage in inferred_stages:
        cost = actual_by_stage.get(stage)
        if cost is not None:
            normalized.append(CostRecord(
                stage=stage,
                amount_usd=get_model_cost(cost.model, cost.total_tokens),
                amount_tokens=cost.total_tokens,
                source="actual",
            ))
        else:
            fallback_stages.append(stage)
            fallback = _fallback_cost(stage)
            normalized.append(CostRecord(
                stage=stage,
                amount_usd=get_model_cost(fallback.model, fallback.total_tokens),
                amount_tokens=fallback.total_tokens,
                source="fallback_estimate",
                requires_reconciliation=True,
            ))

    if fallback_stages:
        logger.error(
            "canonical_costs_fallback_used",
            phase="finalization",
            session_id=result.session_id,
            stages=fallback_stages,
            severity="high",
        )

    return normalized
```

#### 4c. Replace `_finalize_canonical_success` method (lines 582-691):

```python
async def _finalize_canonical_success(
    self,
    canonical_session_id: int,
    result: PipelineResult,
    title: str,
    word_count: int,
    sources_count: int,
) -> bool:
    async with db_repository.async_session() as session:
        async with session.begin():
            session_repo = BlogSessionRepository(session)
            version_repo = BlogVersionRepository(session)
            budget_repo = BudgetRepository(session)
            run_repo = AgentRunRepository(session)
            review_repo = HumanReviewRepository(session)
            auth_user_repo = AuthUserRepository(session)
            notification_repo = NotificationRepository(session)

            blog_session = await session_repo.get_by_id(canonical_session_id)
            if blog_session is None:
                logger.warning("canonical_session_missing", session_id=canonical_session_id)
                return False

            budget_service = BudgetService(
                budget_repo=budget_repo,
                session_repo=session_repo,
            )
            revision_service = RevisionService(
                session_repo=session_repo,
                version_repo=version_repo,
                review_repo=review_repo,
                budget_repo=budget_repo,
                auth_user_repo=auth_user_repo,
                notification_repo=notification_repo,
            )

            reservation = await budget_repo.get_active_reservation_for_session(
                canonical_session_id, for_update=True
            )
            if reservation is None:
                logger.error("no_active_reservation", session_id=canonical_session_id)
                return False

            try:
                await budget_service.assert_reservation_valid(reservation.id)
            except BudgetError as exc:
                status = (
                    BlogSessionStatus.AWAITING_BUDGET_RESOLUTION
                    if isinstance(exc, BudgetExhausted) and blog_session.status != BlogSessionStatus.BUDGET_EXHAUSTED
                    else BlogSessionStatus.BUDGET_EXHAUSTED
                )
                await session_repo.update_status(
                    canonical_session_id,
                    status=status,
                    current_stage="finalization",
                )
                await budget_service.release(
                    tenant_id=blog_session.tenant_id,
                    end_user_id=blog_session.end_user_id,
                    service_client_id=blog_session.service_client_id,
                    blog_session_id=canonical_session_id,
                    reason=str(exc),
                )
                return False

            cost_records = self._canonical_costs_for_finalization(result)
            finalization_costs = {
                r.stage: r for r in cost_records
                if r.stage not in GATE_COMMITTED_STAGES
            }

            total_finalization_usd = sum(r.amount_usd for r in finalization_costs.values())
            total_finalization_tokens = sum(r.amount_tokens for r in finalization_costs.values())

            try:
                await budget_service.assert_within_reservation(
                    reservation.id,
                    total_finalization_usd,
                    total_finalization_tokens,
                )
            except BudgetError as exc:
                status = (
                    BlogSessionStatus.AWAITING_BUDGET_RESOLUTION
                    if isinstance(exc, BudgetExhausted)
                    else BlogSessionStatus.BUDGET_EXHAUSTED
                )
                await session_repo.update_status(
                    canonical_session_id,
                    status=status,
                    current_stage="finalization",
                )
                await budget_service.release(
                    tenant_id=blog_session.tenant_id,
                    end_user_id=blog_session.end_user_id,
                    service_client_id=blog_session.service_client_id,
                    blog_session_id=canonical_session_id,
                    reason=str(exc),
                )
                return False

            if finalization_costs:
                try:
                    await budget_service.finalize_stage_costs(
                        reservation.id,
                        finalization_costs,
                        tenant_id=blog_session.tenant_id,
                        end_user_id=blog_session.end_user_id,
                        service_client_id=blog_session.service_client_id,
                        blog_session_id=canonical_session_id,
                    )
                except BudgetError as exc:
                    await session_repo.update_status(
                        canonical_session_id,
                        status=BlogSessionStatus.BUDGET_EXHAUSTED,
                        current_stage="finalization",
                    )
                    await budget_service.release(
                        tenant_id=blog_session.tenant_id,
                        end_user_id=blog_session.end_user_id,
                        service_client_id=blog_session.service_client_id,
                        blog_session_id=canonical_session_id,
                        reason=str(exc),
                    )
                    return False

            await revision_service.record_editor_output(
                blog_session_id=canonical_session_id,
                content_markdown=result.final_content,
                title=title or None,
                word_count=word_count,
                sources_count=sources_count,
                editor_approved=bool(
                    isinstance(result.editor_review, dict)
                    and result.editor_review.get("approved")
                ),
            )

            await budget_service.finalize_reservation(
                tenant_id=blog_session.tenant_id,
                end_user_id=blog_session.end_user_id,
                service_client_id=blog_session.service_client_id,
                blog_session_id=canonical_session_id,
                reason="pipeline_completed",
            )
    return True
```

### 5. MODIFY: `backend/src/monitoring/metrics.py`

Add after the existing budget metrics (after line 104):

```python
budget_finalization_overspend_delta = Histogram(
    "budget_finalization_overspend_delta",
    "Overspend delta (actual - reserved) on each finalization, in USD",
)

budget_fallback_cost_total = Counter(
    "budget_fallback_cost_total",
    "Total fallback cost records committed to the ledger",
    ["stage"],
)
```

### 6. MODIFY: `backend/src/services/budget_service.py` — Update `finalize_reservation`

The existing `finalize_reservation` method (lines 581-617) stays as-is. It is called at the end of `_finalize_canonical_success` to release unused reservation and mark it COMMITTED. The new `assert_*` and `finalize_stage_costs` methods are called BEFORE it.

---

## Execution Order

1. Create `budget_exceptions.py` (no dependencies)
2. Add Prometheus metrics to `metrics.py` (no dependencies)
3. Add repository methods to `budget_repository.py`
4. Add `CostRecord`, tolerance, and new methods to `budget_service.py`
5. Rewrite `_finalize_canonical_success` and `_canonical_costs_for_finalization` in `stage_executor.py`
6. Run lint and typecheck
