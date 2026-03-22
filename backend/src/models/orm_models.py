"""Canonical domain ORM models for blogify-ai-adk.

Phase 1: New canonical tables added alongside existing legacy tables.
Legacy tables (users, blogs, cost_records) remain untouched.

New canonical model hierarchy:
  ServiceClient → Tenant → EndUser
  EndUser + Tenant → BudgetPolicy
  BudgetLedgerEntry references Tenant, EndUser, BlogSession, BlogVersion, AgentRun
  BlogSession → (many) BlogVersion
  BlogSession → (many) AgentRun
  BlogVersion → (many) HumanReviewEvent
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum as PyEnum
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """Shared base class for all ORM models."""
    pass


# ---------------------------------------------------------------------------
# Legacy tables (Phase 0 — unchanged)
# ---------------------------------------------------------------------------


class User(Base):
    """User model for budget tracking (legacy)."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    daily_budget_usd: Mapped[float] = mapped_column(Float, default=1.0)
    daily_blogs_limit: Mapped[int] = mapped_column(Integer, default=10)

    total_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    total_blogs_generated: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    blogs: Mapped[list["Blog"]] = relationship("Blog", back_populates="user")
    cost_records: Mapped[list["CostRecord"]] = relationship("CostRecord", back_populates="user")


class Blog(Base):
    """Generated blog record (legacy)."""

    __tablename__ = "blogs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(255), ForeignKey("users.user_id"), nullable=False)
    session_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)

    topic: Mapped[str] = mapped_column(String(500), nullable=False)
    audience: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    word_count: Mapped[int] = mapped_column(Integer, default=0)
    sources_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(50), default="in_progress")
    current_stage: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    stage_data: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    total_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship("User", back_populates="blogs")
    cost_records: Mapped[list["CostRecord"]] = relationship("CostRecord", back_populates="blog")


class CostRecord(Base):
    """Cost tracking per agent invocation (legacy)."""

    __tablename__ = "cost_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(255), ForeignKey("users.user_id"), nullable=False)
    blog_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("blogs.id"), nullable=True)
    session_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)

    agent_name: Mapped[str] = mapped_column(String(100), nullable=False)
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)

    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)

    latency_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    user: Mapped["User"] = relationship("User", back_populates="cost_records")
    blog: Mapped[Optional["Blog"]] = relationship("Blog", back_populates="cost_records")


# ---------------------------------------------------------------------------
# Canonical tables (Phase 1 — new)
# ---------------------------------------------------------------------------


class ClientMode(str, PyEnum):
    STANDALONE = "standalone"
    BLOGIFY_SERVICE = "blogify_service"


class ClientStatus(str, PyEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    ROTATED = "rotated"


class ServiceClient(Base):
    """Represents calling systems / deploy modes."""

    __tablename__ = "service_clients"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    client_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    mode: Mapped[str] = mapped_column(
        Enum(ClientMode, name="client_mode_enum"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    hashed_api_key: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(
        Enum(ClientStatus, name="client_status_enum"),
        nullable=False,
        default=ClientStatus.ACTIVE,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    rotated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    tenants: Mapped[list["Tenant"]] = relationship("Tenant", back_populates="service_client")


class TenantPlan(str, PyEnum):
    FREE = "free"
    PRO = "pro"
    ENTERPRISE = "enterprise"


class TenantStatus(str, PyEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    CANCELLED = "cancelled"


class Tenant(Base):
    """Budget and account boundary."""

    __tablename__ = "tenants"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    service_client_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("service_clients.id"), nullable=False
    )
    external_tenant_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    plan_tier: Mapped[str] = mapped_column(
        Enum(TenantPlan, name="tenant_plan_enum"), nullable=False, default=TenantPlan.FREE
    )
    status: Mapped[str] = mapped_column(
        Enum(TenantStatus, name="tenant_status_enum"),
        nullable=False,
        default=TenantStatus.ACTIVE,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    service_client: Mapped["ServiceClient"] = relationship(
        "ServiceClient", back_populates="tenants"
    )
    end_users: Mapped[list["EndUser"]] = relationship("EndUser", back_populates="tenant")
    budget_policies: Mapped[list["BudgetPolicy"]] = relationship(
        "BudgetPolicy", back_populates="tenant"
    )
    blog_sessions: Mapped[list["BlogSession"]] = relationship(
        "BlogSession", back_populates="tenant"
    )


class EndUserStatus(str, PyEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"


class EndUser(Base):
    """The actual budget-consuming user."""

    __tablename__ = "end_users"
    __table_args__ = (UniqueConstraint("tenant_id", "external_user_id", name="uq_tenant_user"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    external_user_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    display_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(
        Enum(EndUserStatus, name="end_user_status_enum"),
        nullable=False,
        default=EndUserStatus.ACTIVE,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    tenant: Mapped["Tenant"] = relationship("Tenant", back_populates="end_users")
    budget_policies: Mapped[list["BudgetPolicy"]] = relationship(
        "BudgetPolicy", back_populates="end_user"
    )
    budget_ledger_entries: Mapped[list["BudgetLedgerEntry"]] = relationship(
        "BudgetLedgerEntry", back_populates="end_user"
    )
    blog_sessions: Mapped[list["BlogSession"]] = relationship(
        "BlogSession", back_populates="end_user"
    )


class BudgetPolicyScope(str, PyEnum):
    DEFAULT = "default"
    TENANT = "tenant"
    USER_OVERRIDE = "user_override"


class BudgetPolicy(Base):
    """Configured budget limits per scope (default / tenant / user override)."""

    __tablename__ = "budget_policies"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("tenants.id"), nullable=True
    )
    end_user_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("end_users.id"), nullable=True
    )
    scope: Mapped[str] = mapped_column(
        Enum(BudgetPolicyScope, name="budget_scope_enum"),
        nullable=False,
        default=BudgetPolicyScope.DEFAULT,
    )

    # Daily limits
    daily_cost_limit_usd: Mapped[float] = mapped_column(Float, default=1.0)
    daily_token_limit: Mapped[int] = mapped_column(Integer, default=50_000)
    daily_blog_limit: Mapped[int] = mapped_column(Integer, default=5)

    # Per-session limits
    per_session_cost_limit_usd: Mapped[float] = mapped_column(Float, default=0.10)
    per_session_token_limit: Mapped[int] = mapped_column(Integer, default=15_000)
    max_revision_iterations_per_session: Mapped[int] = mapped_column(Integer, default=3)
    max_concurrent_sessions: Mapped[int] = mapped_column(Integer, default=2)

    soft_stop_enabled: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    tenant: Mapped[Optional["Tenant"]] = relationship(
        "Tenant", back_populates="budget_policies"
    )
    end_user: Mapped[Optional["EndUser"]] = relationship(
        "EndUser", back_populates="budget_policies"
    )


class LedgerEntryType(str, PyEnum):
    RESERVE = "reserve"
    COMMIT = "commit"
    RELEASE = "release"
    ADJUSTMENT = "adjustment"
    REFUND = "refund"
    REJECT = "reject"


class LedgerResourceType(str, PyEnum):
    TOKENS = "tokens"
    USD = "usd"
    BLOG_COUNT = "blog_count"
    REVISION_COUNT = "revision_count"


class BudgetLedgerEntry(Base):
    """Canonical usage journal — immutable append-only record."""

    __tablename__ = "budget_ledger_entries"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    end_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("end_users.id"), nullable=False
    )
    blog_session_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("blog_sessions.id"), nullable=True
    )
    blog_version_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("blog_versions.id"), nullable=True
    )
    agent_run_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("agent_runs.id"), nullable=True
    )

    entry_type: Mapped[str] = mapped_column(
        Enum(LedgerEntryType, name="ledger_entry_type_enum"), nullable=False
    )
    resource_type: Mapped[str] = mapped_column(
        Enum(LedgerResourceType, name="ledger_resource_type_enum"), nullable=False
    )
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    unit_cost_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    metadata_: Mapped[Optional[dict]] = mapped_column("metadata", JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    end_user: Mapped["EndUser"] = relationship(
        "EndUser", back_populates="budget_ledger_entries"
    )


class BlogSessionStatus(str, PyEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    AWAITING_HUMAN_REVIEW = "awaiting_human_review"
    REVISION_REQUESTED = "revision_requested"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    BUDGET_EXHAUSTED = "budget_exhausted"


class BlogSession(Base):
    """Canonical parent record for a blog generation request and its full lifecycle."""

    __tablename__ = "blog_sessions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    end_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("end_users.id"), nullable=False
    )
    service_client_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("service_clients.id"), nullable=False
    )

    # Request identity
    external_request_id: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, index=True
    )
    external_blog_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Content parameters
    topic: Mapped[str] = mapped_column(String(500), nullable=False)
    audience: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    tone: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # Lifecycle
    status: Mapped[str] = mapped_column(
        Enum(BlogSessionStatus, name="blog_session_status_enum"),
        nullable=False,
        default=BlogSessionStatus.QUEUED,
        index=True,
    )
    current_stage: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    iteration_count: Mapped[int] = mapped_column(Integer, default=0)

    # Budget tracking
    budget_reserved_usd: Mapped[float] = mapped_column(Float, default=0.0)
    budget_reserved_tokens: Mapped[int] = mapped_column(Integer, default=0)
    budget_spent_usd: Mapped[float] = mapped_column(Float, default=0.0)
    budget_spent_tokens: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    tenant: Mapped["Tenant"] = relationship("Tenant", back_populates="blog_sessions")
    end_user: Mapped["EndUser"] = relationship("EndUser", back_populates="blog_sessions")
    versions: Mapped[list["BlogVersion"]] = relationship(
        "BlogVersion", back_populates="session", order_by="BlogVersion.version_number"
    )
    agent_runs: Mapped[list["AgentRun"]] = relationship(
        "AgentRun", back_populates="session"
    )


class BlogVersionSource(str, PyEnum):
    INITIAL_GENERATION = "initial_generation"
    HUMAN_REVISION = "human_revision"
    CHAT_EDIT = "chat_edit"
    MANUAL_IMPORT = "manual_import"


class BlogEditorStatus(str, PyEnum):
    DRAFT = "draft"
    EDITOR_APPROVED = "editor_approved"
    HUMAN_APPROVED = "human_approved"
    HUMAN_REJECTED = "human_rejected"


class BlogCreatedBy(str, PyEnum):
    SYSTEM = "system"
    HUMAN = "human"
    CHATBOT = "chatbot"


class BlogVersion(Base):
    """Every material output revision of a blog — the "final blog" is the latest approved version."""

    __tablename__ = "blog_versions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    blog_session_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("blog_sessions.id"), nullable=False, index=True
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    source_type: Mapped[str] = mapped_column(
        Enum(BlogVersionSource, name="blog_version_source_enum"), nullable=False
    )

    title: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    content_markdown: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    word_count: Mapped[int] = mapped_column(Integer, default=0)
    sources_count: Mapped[int] = mapped_column(Integer, default=0)

    editor_status: Mapped[str] = mapped_column(
        Enum(BlogEditorStatus, name="blog_editor_status_enum"),
        nullable=False,
        default=BlogEditorStatus.DRAFT,
    )
    created_by: Mapped[str] = mapped_column(
        Enum(BlogCreatedBy, name="blog_created_by_enum"),
        nullable=False,
        default=BlogCreatedBy.SYSTEM,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    session: Mapped["BlogSession"] = relationship("BlogSession", back_populates="versions")
    agent_runs: Mapped[list["AgentRun"]] = relationship(
        "AgentRun", back_populates="blog_version"
    )
    human_review_events: Mapped[list["HumanReviewEvent"]] = relationship(
        "HumanReviewEvent", back_populates="blog_version"
    )


class AgentRunStatus(str, PyEnum):
    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"


class AgentRun(Base):
    """Structured metadata for each stage/agent execution."""

    __tablename__ = "agent_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    blog_session_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("blog_sessions.id"), nullable=False, index=True
    )
    blog_version_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("blog_versions.id"), nullable=True
    )
    parent_agent_run_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("agent_runs.id"), nullable=True
    )

    stage_name: Mapped[str] = mapped_column(String(80), nullable=False)
    agent_name: Mapped[str] = mapped_column(String(100), nullable=False)
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)

    status: Mapped[str] = mapped_column(
        Enum(AgentRunStatus, name="agent_run_status_enum"),
        nullable=False,
        default=AgentRunStatus.STARTED,
    )

    # Artifact storage URIs — full prompt/response go to artifact store, not DB
    prompt_artifact_uri: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    response_artifact_uri: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)

    # Summaries and counts stay in DB for observability
    input_summary: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    output_summary: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    session: Mapped["BlogSession"] = relationship("BlogSession", back_populates="agent_runs")
    blog_version: Mapped[Optional["BlogVersion"]] = relationship(
        "BlogVersion", back_populates="agent_runs"
    )
    ledger_entries: Mapped[list["BudgetLedgerEntry"]] = relationship(
        "BudgetLedgerEntry",
        primaryjoin="AgentRun.id == foreign(BudgetLedgerEntry.agent_run_id)",
        viewonly=True,
    )


class HumanReviewAction(str, PyEnum):
    APPROVE = "approve"
    REQUEST_REVISION = "request_revision"
    REJECT = "reject"
    REOPEN = "reopen"


class HumanReviewEvent(Base):
    """HITL interactions — one record per reviewer action."""

    __tablename__ = "human_review_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    blog_session_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("blog_sessions.id"), nullable=False, index=True
    )
    blog_version_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("blog_versions.id"), nullable=False
    )
    reviewer_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    action: Mapped[str] = mapped_column(
        Enum(HumanReviewAction, name="human_review_action_enum"), nullable=False
    )
    feedback_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    review_context: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    blog_version: Mapped["BlogVersion"] = relationship(
        "BlogVersion", back_populates="human_review_events"
    )


class ExportFormat(str, PyEnum):
    PDF = "pdf"
    DOCX = "docx"
    MARKDOWN = "markdown"


class ExportStatus(str, PyEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class ExportJob(Base):
    """Standalone export jobs — standalone mode only."""

    __tablename__ = "export_jobs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    blog_version_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("blog_versions.id"), nullable=False
    )
    format: Mapped[str] = mapped_column(
        Enum(ExportFormat, name="export_format_enum"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        Enum(ExportStatus, name="export_status_enum"),
        nullable=False,
        default=ExportStatus.PENDING,
    )
    artifact_uri: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
