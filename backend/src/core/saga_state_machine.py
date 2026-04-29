"""Saga-pattern state machine for blog session lifecycle.

Enforces valid state transitions and prevents illegal state changes.
Every status mutation in the system MUST pass through ``validate()``
before being applied to the database.

Transition map:
    QUEUED → PROCESSING | CANCELLED | FAILED
    PROCESSING → AWAITING_OUTLINE_REVIEW | AWAITING_FINAL_REVIEW |
                 COMPLETED | FAILED | QUEUED | CANCELLED
    AWAITING_OUTLINE_REVIEW → QUEUED | CANCELLED | FAILED
    AWAITING_FINAL_REVIEW → COMPLETED | REVISION_REQUESTED | FAILED
    REVISION_REQUESTED → PROCESSING | CANCELLED | FAILED
    COMPLETED, FAILED, CANCELLED → (terminal — no outbound transitions)
"""

from __future__ import annotations

from src.config.logging_config import get_logger
from src.core.errors import BlogifyError, ErrorCode
from src.models.orm_models import BlogSessionStatus as S

logger = get_logger(__name__)

# ── Ordered stage list for the pipeline ────────────────────────────────
PIPELINE_STAGES: list[str] = ["intent", "outline", "research", "writer", "editor"]

# Stages where user-initiated cancellation is allowed
CANCELLABLE_STAGES: frozenset[str] = frozenset({"intent", "outline", "research"})

# Maximum number of human revision rounds before auto-completing
MAX_REVISION_COUNT: int = 3

# ── Transition map ─────────────────────────────────────────────────────
VALID_TRANSITIONS: dict[S, frozenset[S]] = {
    S.QUEUED: frozenset({
        S.PROCESSING,
        S.CANCELLED,
        S.FAILED,
    }),
    S.PROCESSING: frozenset({
        S.AWAITING_OUTLINE_REVIEW,
        S.AWAITING_FINAL_REVIEW,
        S.COMPLETED,
        S.FAILED,
        S.QUEUED,       # reaper requeue or retry
        S.CANCELLED,    # user cancel (pre-writer stages only)
    }),
    S.AWAITING_OUTLINE_REVIEW: frozenset({
        S.QUEUED,       # outline approved → re-enqueue
        S.CANCELLED,
        S.FAILED,
    }),
    S.AWAITING_FINAL_REVIEW: frozenset({
        S.COMPLETED,           # human approves final blog
        S.REVISION_REQUESTED,  # human requests changes
        S.FAILED,
    }),
    S.REVISION_REQUESTED: frozenset({
        S.PROCESSING,   # worker picks up revision from writer stage
        S.CANCELLED,
        S.FAILED,
    }),
    # Terminal states — no outbound transitions
    S.COMPLETED: frozenset(),
    S.FAILED:    frozenset(),
    S.CANCELLED: frozenset(),
}

# States from which user-initiated cancellation is possible
CANCELLABLE_STATUSES: frozenset[S] = frozenset({
    S.QUEUED,
    S.AWAITING_OUTLINE_REVIEW,
    S.REVISION_REQUESTED,
    # S.PROCESSING is conditionally cancellable — only when current_stage
    # is in CANCELLABLE_STAGES. Checked separately in is_cancellable().
})

# Terminal states — no further processing possible
TERMINAL_STATUSES: frozenset[S] = frozenset({S.COMPLETED, S.FAILED, S.CANCELLED})


class IllegalStateTransition(BlogifyError):
    """Raised when a state transition violates the saga transition map."""

    def __init__(
        self,
        from_status: S,
        to_status: S,
        session_id: int | None = None,
        reason: str | None = None,
    ) -> None:
        detail = (
            f"Illegal transition {from_status.value} → {to_status.value}"
            f"{f' for session {session_id}' if session_id else ''}"
            f"{f': {reason}' if reason else ''}"
        )
        super().__init__(
            message=detail,
            error_code=ErrorCode.VALIDATION_ERROR,
            status_code=409,
            details={
                "from_status": from_status.value,
                "to_status": to_status.value,
                "session_id": session_id,
            },
        )
        self.from_status = from_status
        self.to_status = to_status


class SagaStateMachine:
    """Validates blog session state transitions against the saga map."""

    @staticmethod
    def validate(
        from_status: S,
        to_status: S,
        session_id: int | None = None,
    ) -> None:
        """Raise ``IllegalStateTransition`` if the move is not allowed.

        Call this before every status mutation in the repository layer.
        """
        allowed = VALID_TRANSITIONS.get(from_status, frozenset())
        if to_status not in allowed:
            logger.warning(
                "illegal_state_transition_blocked",
                from_status=from_status.value,
                to_status=to_status.value,
                session_id=session_id,
            )
            raise IllegalStateTransition(from_status, to_status, session_id)

    @staticmethod
    def is_terminal(status: S) -> bool:
        """Return True if the status is a terminal (no-exit) state."""
        return status in TERMINAL_STATUSES

    @staticmethod
    def is_cancellable(status: S, current_stage: str | None = None) -> bool:
        """Check whether a session in the given state+stage can be cancelled.

        Cancellation rules:
        - QUEUED, AWAITING_OUTLINE_REVIEW, REVISION_REQUESTED → always cancellable
        - PROCESSING → only if current_stage is in {intent, outline, research}
        - All other states → not cancellable
        """
        if status in CANCELLABLE_STATUSES:
            return True
        if status == S.PROCESSING:
            return current_stage in CANCELLABLE_STAGES
        return False

    @staticmethod
    def can_request_revision(iteration_count: int) -> bool:
        """Check whether another revision round is allowed.

        Capped at ``MAX_REVISION_COUNT`` to prevent infinite revision loops.
        """
        return iteration_count < MAX_REVISION_COUNT
