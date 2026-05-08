"""Canonical V1 ORM models - auth_users, blog_sessions, agent_runs, budget_ledger."""

import enum
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Index,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class BlogSessionStatus(str, enum.Enum):
    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    AWAITING_OUTLINE_REVIEW = "AWAITING_OUTLINE_REVIEW"
    AWAITING_FINAL_REVIEW = "AWAITING_FINAL_REVIEW"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class BudgetEntryType(str, enum.Enum):
    GRANT = "GRANT"
    RESERVE = "RESERVE"
    COMMIT = "COMMIT"
    RELEASE = "RELEASE"
    ADJUSTMENT = "ADJUSTMENT"


class AgentRunStatus(str, enum.Enum):
    STARTED = "STARTED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


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
    status: Mapped[str] = mapped_column(
        Enum(BlogSessionStatus, values_callable=lambda e: [x.value for x in e], native_enum=False),
        nullable=False,
        default=BlogSessionStatus.QUEUED,
    )
    current_stage: Mapped[str | None] = mapped_column(String(50), nullable=True)

    adk_session_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    invocation_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    confirmation_request_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    outline_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    final_content: Mapped[str | None] = mapped_column(Text, nullable=True)

    budget_reserved_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    budget_spent_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    budget_reserved_usd: Mapped[Decimal] = mapped_column(Numeric(12, 8), nullable=False, default=Decimal("0"))
    budget_spent_usd: Mapped[Decimal] = mapped_column(Numeric(12, 8), nullable=False, default=Decimal("0"))

    reap_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)
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
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("auth_users.id"), nullable=False)
    blog_session_id: Mapped[int] = mapped_column(Integer, ForeignKey("blog_sessions.id"), nullable=False)
    stage_name: Mapped[str] = mapped_column(String(100), nullable=False)
    agent_name: Mapped[str] = mapped_column(String(100), nullable=False)
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(
        Enum(AgentRunStatus, values_callable=lambda e: [x.value for x in e], native_enum=False),
        nullable=False,
        default=AgentRunStatus.STARTED,
    )
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 8), nullable=False, default=Decimal("0"))
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("blog_session_id", "stage_name", name="uq_agent_runs_session_stage"),
        Index("ix_agent_runs_session", "blog_session_id"),
        Index("ix_agent_runs_user_id", "user_id"),
    )


class BudgetLedger(Base):
    __tablename__ = "budget_ledger"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("auth_users.id"), nullable=False)
    blog_session_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("blog_sessions.id"), nullable=True)
    agent_run_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("agent_runs.id"), nullable=True)
    entry_type: Mapped[str] = mapped_column(
        Enum(BudgetEntryType, values_callable=lambda e: [x.value for x in e], native_enum=False),
        nullable=False,
    )
    tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    amount_usd: Mapped[Decimal] = mapped_column(Numeric(12, 8), nullable=False, default=Decimal("0"))
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    __table_args__ = (
        Index("ix_budget_ledger_user_id", "user_id"),
        Index("ix_budget_ledger_session", "blog_session_id"),
    )


class ResearchSource(Base):
    """Stores research sources from Tavily for each blog session."""

    __tablename__ = "research_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("auth_users.id"), nullable=False)
    blog_session_id: Mapped[int] = mapped_column(Integer, ForeignKey("blog_sessions.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=True)
    score: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False, default=0.0)
    topic: Mapped[str] = mapped_column(String(500), nullable=True)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    __table_args__ = (
        Index("ix_research_sources_session", "blog_session_id"),
        Index("ix_research_sources_user", "user_id"),
    )


class LeaseEventType:
    """Lease event types for audit trail."""
    ACQUIRED = "ACQUIRED"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"
    HEARTBEAT_FAILED = "HEARTBEAT_FAILED"
    REAPED = "REAPED"


class SessionLease(Base):
    """Lease ownership for sessions - append-only audit trail.
    
    Each row represents a lease acquisition. Multiple rows per session
    create a complete audit trail of handoffs between workers.
    """
    __tablename__ = "session_leases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    blog_session_id: Mapped[int] = mapped_column(Integer, ForeignKey("blog_sessions.id"), nullable=False)
    lease_owner: Mapped[str] = mapped_column(String(255), nullable=False)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    release_reason: Mapped[str | None] = mapped_column(String(50), nullable=True)

    __table_args__ = (
        Index("ix_session_leases_session", "blog_session_id"),
        Index("ix_session_leases_owner", "lease_owner"),
        Index("ix_session_leases_started", "started_at"),
        Index("ix_session_leases_ended", "ended_at"),
    )