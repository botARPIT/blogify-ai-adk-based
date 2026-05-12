"""V1 schema - fresh start for blogify-ai-adk.

Revision ID: 100
Revises:
Create Date: 2025-01-01 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "100"
down_revision: str | Sequence[str] | None = "014_add_schema_defaults"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # This migration documents the V1 schema state but is a no-op
    # because all tables and types were already created by migrations 001-014.
    # Migration 015+ will build on top of this baseline.
    pass
        "auth_users",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_index("ix_auth_users_email", "auth_users", ["email"])

    op.create_table(
        "blog_sessions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("topic", sa.String(length=500), nullable=False),
        sa.Column(
            "audience", sa.String(length=255), nullable=False, server_default="general readers"
        ),
        sa.Column("tone", sa.String(length=100), nullable=False, server_default="professional"),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="QUEUED"),
        sa.Column("current_stage", sa.String(length=50), nullable=True),
        sa.Column("adk_session_id", sa.String(length=255), nullable=True),
        sa.Column("invocation_id", sa.String(length=255), nullable=True),
        sa.Column("confirmation_request_id", sa.String(length=255), nullable=True),
        sa.Column("outline_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("final_content", sa.Text(), nullable=True),
        sa.Column("budget_reserved_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("budget_spent_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "budget_reserved_usd",
            sa.Numeric(precision=12, scale=8),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "budget_spent_usd",
            sa.Numeric(precision=12, scale=8),
            nullable=False,
            server_default="0",
        ),
        sa.Column("reap_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["auth_users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "idempotency_key", name="uq_blog_sessions_idempotency"),
    )
    op.create_index("ix_blog_sessions_user_id", "blog_sessions", ["user_id"])
    op.create_index("ix_blog_sessions_status", "blog_sessions", ["status"])

    op.create_table(
        "agent_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("blog_session_id", sa.Integer(), nullable=False),
        sa.Column("stage_name", sa.String(length=100), nullable=False),
        sa.Column("agent_name", sa.String(length=100), nullable=False),
        sa.Column("model_name", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="STARTED"),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "cost_usd", sa.Numeric(precision=12, scale=8), nullable=False, server_default="0"
        ),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("output_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["auth_users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["blog_session_id"], ["blog_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("blog_session_id", "stage_name", name="uq_agent_runs_session_stage"),
    )
    op.create_index("ix_agent_runs_session", "agent_runs", ["blog_session_id"])
    op.create_index("ix_agent_runs_user_id", "agent_runs", ["user_id"])

    op.create_table(
        "budget_ledger",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("blog_session_id", sa.Integer(), nullable=True),
        sa.Column("agent_run_id", sa.Integer(), nullable=True),
        sa.Column("entry_type", sa.String(length=50), nullable=False),
        sa.Column("tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "amount_usd", sa.Numeric(precision=12, scale=8), nullable=False, server_default="0"
        ),
        sa.Column("note", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["auth_users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["blog_session_id"], ["blog_sessions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["agent_run_id"], ["agent_runs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_budget_ledger_user_id", "budget_ledger", ["user_id"])
    op.create_index("ix_budget_ledger_session", "budget_ledger", ["blog_session_id"])

    op.create_table(
        "research_sources",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("blog_session_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("score", sa.Numeric(precision=5, scale=4), nullable=False, server_default="0"),
        sa.Column("topic", sa.String(length=500), nullable=True),
        sa.Column(
            "collected_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["auth_users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["blog_session_id"], ["blog_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_research_sources_session", "research_sources", ["blog_session_id"])
    op.create_index("ix_research_sources_user", "research_sources", ["user_id"])

    op.create_table(
        "session_leases",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("blog_session_id", sa.Integer(), nullable=False),
        sa.Column("lease_owner", sa.String(length=255), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("release_reason", sa.String(length=50), nullable=True),
        sa.ForeignKeyConstraint(["blog_session_id"], ["blog_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_session_leases_session", "session_leases", ["blog_session_id"])
    op.create_index("ix_session_leases_owner", "session_leases", ["lease_owner"])
    op.create_index("ix_session_leases_started", "session_leases", ["started_at"])
    op.create_index("ix_session_leases_ended", "session_leases", ["ended_at"])


def downgrade() -> None:
    op.drop_table("session_leases")
    op.drop_table("research_sources")
    op.drop_table("budget_ledger")
    op.drop_table("agent_runs")
    op.drop_table("blog_sessions")
    op.drop_table("auth_users")
    op.execute("DROP TYPE IF EXISTS agentrunstatus")
    op.execute("DROP TYPE IF EXISTS budgetentrytype")
    op.execute("DROP TYPE IF EXISTS blogsessionstatus")
