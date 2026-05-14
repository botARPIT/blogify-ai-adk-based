"""Canonical V1 ORM models - all tables use plain VARCHAR for status fields."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class StrEnum(str, Enum):
    """Base for string-valued enums — safe for DB VARCHAR storage."""

    pass


class BlogSessionStatus(StrEnum):
    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    AWAITING_OUTLINE_REVIEW = "AWAITING_OUTLINE_REVIEW"
    AWAITING_FINAL_REVIEW = "AWAITING_FINAL_REVIEW"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class BudgetEntryType(StrEnum):
    GRANT = "GRANT"
    RESERVE = "RESERVE"
    COMMIT = "COMMIT"
    RELEASE = "RELEASE"
    ADJUSTMENT = "ADJUSTMENT"


class AgentRunStatus(StrEnum):
    STARTED = "STARTED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ReservationStatus(StrEnum):
    ACTIVE = "ACTIVE"
    COMMITTED = "COMMITTED"
    RELEASED = "RELEASED"


class LeaseEventType:
    """Lease event type constants for audit trail values — not persisted as enum."""

    ACQUIRED = "ACQUIRED"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"
    HEARTBEAT_FAILED = "HEARTBEAT_FAILED"
    REAPED = "REAPED"


class AuthUser(Base):
    __tablename__ = "auth_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BlogSession(Base):
    __tablename__ = "blog_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("auth_users.id"), nullable=False)
    topic: Mapped[str] = mapped_column(String(500), nullable=False)
    audience: Mapped[str] = mapped_column(String(255), nullable=False, default="general readers")
    tone: Mapped[str] = mapped_column(String(100), nullable=False, default="professional")
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="QUEUED")
    current_stage: Mapped[str | None] = mapped_column(String(50), nullable=True)

    adk_session_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    invocation_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    confirmation_request_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    outline_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    final_content: Mapped[str | None] = mapped_column(Text, nullable=True)

    budget_reserved_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    budget_spent_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    budget_reserved_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 8), nullable=False, default=Decimal("0")
    )
    budget_spent_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 8), nullable=False, default=Decimal("0")
    )

    reap_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key", name="uq_blog_sessions_idempotency"),
        Index("ix_blog_sessions_user_id", "user_id"),
        Index("ix_blog_sessions_status", "status"),
    )


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    blog_session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("blog_sessions.id", ondelete="CASCADE"), nullable=False
    )
    stage_name: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="STARTED")
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 8), nullable=False, default=Decimal("0"))
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_agent_runs_session", "blog_session_id"),)


class BudgetLedger(Base):
    __tablename__ = "budget_ledger"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("auth_users.id"), nullable=False)
    blog_session_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("blog_sessions.id"), nullable=True
    )
    agent_run_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("agent_runs.id"), nullable=True
    )
    entry_type: Mapped[str] = mapped_column(String(50), nullable=False)
    tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    amount_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 8), nullable=False, default=Decimal("0")
    )
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    __table_args__ = (
        Index("ix_budget_ledger_user_id", "user_id"),
        Index("ix_budget_ledger_session", "blog_session_id"),
    )


class BudgetAccount(Base):
    """Single source-of-truth balance per user.

    One row per user. Updated atomically at every terminal budget event:
      GRANT   -> balance_usd += amount, total_granted_usd += amount
      RESERVE -> reserved_usd += amount  (via SessionReservation; row not touched here)
      COMMIT  -> reserved_usd -= reserved_amount; balance_usd -= actual_usd; total_spent_usd += actual_usd
      RELEASE -> reserved_usd -= excess_usd  (balance_usd unchanged for excess release)

    available_usd = balance_usd - reserved_usd
    """

    __tablename__ = "budget_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("auth_users.id"), nullable=False, unique=True
    )
    balance_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 8), nullable=False, default=Decimal("0")
    )
    reserved_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 8), nullable=False, default=Decimal("0")
    )
    total_granted_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 8), nullable=False, default=Decimal("0")
    )
    total_spent_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 8), nullable=False, default=Decimal("0")
    )
    last_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    __table_args__ = (Index("ix_budget_accounts_user_id", "user_id"),)


class SessionReservation(Base):
    """Per-session budget reservation record.

    Created when a session's budget is reserved (check_and_reserve).
    Updated to COMMITTED or RELEASED at terminal budget events.
    Used by BudgetService to calculate per-session excess on release.
    """

    __tablename__ = "session_reservations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    blog_session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("blog_sessions.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    reserved_usd: Mapped[Decimal] = mapped_column(Numeric(12, 8), nullable=False)
    reserved_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_session_reservations_session", "blog_session_id"),)


class ResearchSource(Base):
    """Stores research sources from Tavily for each blog session."""

    __tablename__ = "research_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    blog_session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("blog_sessions.id", ondelete="CASCADE"), nullable=False
    )
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    __table_args__ = (Index("ix_research_sources_session", "blog_session_id"),)


class SessionLease(Base):
    """Lease ownership for sessions - append-only audit trail.

    Each row represents a lease acquisition. Multiple rows per session
    create a complete audit trail of handoffs between workers.
    """

    __tablename__ = "session_leases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    blog_session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("blog_sessions.id"), nullable=False
    )
    lease_owner: Mapped[str] = mapped_column(String(255), nullable=False)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    lease_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    release_reason: Mapped[str | None] = mapped_column(String(50), nullable=True)

    __table_args__ = (
        Index("ix_session_leases_session", "blog_session_id"),
        Index("ix_session_leases_owner", "lease_owner"),
        Index("ix_session_leases_started", "started_at"),
        Index("ix_session_leases_ended", "ended_at"),
    )
