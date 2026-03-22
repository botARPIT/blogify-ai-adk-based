"""Alembic migration: 001 — Add canonical domain tables (Phase 1).

Adds 9 new canonical tables alongside the 3 existing legacy tables.
The legacy tables (users, blogs, cost_records) are NOT modified.

Migration is additive and reversible.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# Revision identifiers
revision = "001_canonical_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # Enumerations
    # ------------------------------------------------------------------
    client_mode = postgresql.ENUM(
        "standalone", "blogify_service", name="client_mode_enum", create_type=False
    )
    client_mode.create(op.get_bind(), checkfirst=True)

    client_status = postgresql.ENUM(
        "active", "suspended", "rotated", name="client_status_enum", create_type=False
    )
    client_status.create(op.get_bind(), checkfirst=True)

    tenant_plan = postgresql.ENUM(
        "free", "pro", "enterprise", name="tenant_plan_enum", create_type=False
    )
    tenant_plan.create(op.get_bind(), checkfirst=True)

    tenant_status = postgresql.ENUM(
        "active", "suspended", "cancelled", name="tenant_status_enum", create_type=False
    )
    tenant_status.create(op.get_bind(), checkfirst=True)

    end_user_status = postgresql.ENUM(
        "active", "suspended", name="end_user_status_enum", create_type=False
    )
    end_user_status.create(op.get_bind(), checkfirst=True)

    budget_scope = postgresql.ENUM(
        "default", "tenant", "user_override", name="budget_scope_enum", create_type=False
    )
    budget_scope.create(op.get_bind(), checkfirst=True)

    ledger_entry_type = postgresql.ENUM(
        "reserve", "commit", "release", "adjustment", "refund", "reject",
        name="ledger_entry_type_enum", create_type=False,
    )
    ledger_entry_type.create(op.get_bind(), checkfirst=True)

    ledger_resource_type = postgresql.ENUM(
        "tokens", "usd", "blog_count", "revision_count",
        name="ledger_resource_type_enum", create_type=False,
    )
    ledger_resource_type.create(op.get_bind(), checkfirst=True)

    blog_session_status = postgresql.ENUM(
        "queued", "processing", "awaiting_human_review", "revision_requested",
        "completed", "failed", "cancelled", "budget_exhausted",
        name="blog_session_status_enum", create_type=False,
    )
    blog_session_status.create(op.get_bind(), checkfirst=True)

    blog_version_source = postgresql.ENUM(
        "initial_generation", "human_revision", "chat_edit", "manual_import",
        name="blog_version_source_enum", create_type=False,
    )
    blog_version_source.create(op.get_bind(), checkfirst=True)

    blog_editor_status = postgresql.ENUM(
        "draft", "editor_approved", "human_approved", "human_rejected",
        name="blog_editor_status_enum", create_type=False,
    )
    blog_editor_status.create(op.get_bind(), checkfirst=True)

    blog_created_by = postgresql.ENUM(
        "system", "human", "chatbot", name="blog_created_by_enum", create_type=False
    )
    blog_created_by.create(op.get_bind(), checkfirst=True)

    agent_run_status = postgresql.ENUM(
        "started", "completed", "failed", "timed_out", "cancelled",
        name="agent_run_status_enum", create_type=False,
    )
    agent_run_status.create(op.get_bind(), checkfirst=True)

    human_review_action = postgresql.ENUM(
        "approve", "request_revision", "reject", "reopen",
        name="human_review_action_enum", create_type=False,
    )
    human_review_action.create(op.get_bind(), checkfirst=True)

    export_format = postgresql.ENUM(
        "pdf", "docx", "markdown", name="export_format_enum", create_type=False
    )
    export_format.create(op.get_bind(), checkfirst=True)

    export_status = postgresql.ENUM(
        "pending", "processing", "completed", "failed",
        name="export_status_enum", create_type=False,
    )
    export_status.create(op.get_bind(), checkfirst=True)

    # ------------------------------------------------------------------
    # service_clients
    # ------------------------------------------------------------------
    op.create_table(
        "service_clients",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("client_key", sa.String(128), nullable=False),
        sa.Column("mode", client_mode, nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("hashed_api_key", sa.String(255), nullable=False),
        sa.Column("status", client_status, nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_service_clients_client_key", "service_clients", ["client_key"], unique=True)

    # ------------------------------------------------------------------
    # tenants
    # ------------------------------------------------------------------
    op.create_table(
        "tenants",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("service_client_id", sa.BigInteger(), sa.ForeignKey("service_clients.id"), nullable=False),
        sa.Column("external_tenant_id", sa.String(255), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("plan_tier", tenant_plan, nullable=False, server_default="free"),
        sa.Column("status", tenant_status, nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_tenants_external_tenant_id", "tenants", ["external_tenant_id"])

    # ------------------------------------------------------------------
    # end_users
    # ------------------------------------------------------------------
    op.create_table(
        "end_users",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("external_user_id", sa.String(255), nullable=False),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("display_name", sa.String(255), nullable=True),
        sa.Column("status", end_user_status, nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "external_user_id", name="uq_tenant_user"),
    )
    op.create_index("ix_end_users_external_user_id", "end_users", ["external_user_id"])

    # ------------------------------------------------------------------
    # budget_policies
    # ------------------------------------------------------------------
    op.create_table(
        "budget_policies",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=True),
        sa.Column("end_user_id", sa.BigInteger(), sa.ForeignKey("end_users.id"), nullable=True),
        sa.Column("scope", budget_scope, nullable=False, server_default="default"),
        sa.Column("daily_cost_limit_usd", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("daily_token_limit", sa.Integer(), nullable=False, server_default="50000"),
        sa.Column("daily_blog_limit", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("per_session_cost_limit_usd", sa.Float(), nullable=False, server_default="0.10"),
        sa.Column("per_session_token_limit", sa.Integer(), nullable=False, server_default="15000"),
        sa.Column("max_revision_iterations_per_session", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("max_concurrent_sessions", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("soft_stop_enabled", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ------------------------------------------------------------------
    # blog_sessions
    # ------------------------------------------------------------------
    op.create_table(
        "blog_sessions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("end_user_id", sa.BigInteger(), sa.ForeignKey("end_users.id"), nullable=False),
        sa.Column("service_client_id", sa.BigInteger(), sa.ForeignKey("service_clients.id"), nullable=False),
        sa.Column("external_request_id", sa.String(255), nullable=True),
        sa.Column("external_blog_id", sa.String(255), nullable=True),
        sa.Column("topic", sa.String(500), nullable=False),
        sa.Column("audience", sa.String(255), nullable=True),
        sa.Column("tone", sa.String(100), nullable=True),
        sa.Column(
            "status",
            blog_session_status,
            nullable=False,
            server_default="queued",
        ),
        sa.Column("current_stage", sa.String(80), nullable=True),
        sa.Column("iteration_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("budget_reserved_usd", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("budget_reserved_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("budget_spent_usd", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("budget_spent_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_blog_sessions_external_request_id", "blog_sessions", ["external_request_id"])
    op.create_index("ix_blog_sessions_status", "blog_sessions", ["status"])

    # ------------------------------------------------------------------
    # blog_versions
    # ------------------------------------------------------------------
    op.create_table(
        "blog_versions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("blog_session_id", sa.BigInteger(), sa.ForeignKey("blog_sessions.id"), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("source_type", blog_version_source, nullable=False),
        sa.Column("title", sa.String(500), nullable=True),
        sa.Column("content_markdown", sa.Text(), nullable=True),
        sa.Column("word_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sources_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("editor_status", blog_editor_status, nullable=False, server_default="draft"),
        sa.Column("created_by", blog_created_by, nullable=False, server_default="system"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_blog_versions_blog_session_id", "blog_versions", ["blog_session_id"])

    # ------------------------------------------------------------------
    # agent_runs
    # ------------------------------------------------------------------
    op.create_table(
        "agent_runs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("blog_session_id", sa.BigInteger(), sa.ForeignKey("blog_sessions.id"), nullable=False),
        sa.Column("blog_version_id", sa.BigInteger(), sa.ForeignKey("blog_versions.id"), nullable=True),
        sa.Column("parent_agent_run_id", sa.BigInteger(), sa.ForeignKey("agent_runs.id"), nullable=True),
        sa.Column("stage_name", sa.String(80), nullable=False),
        sa.Column("agent_name", sa.String(100), nullable=False),
        sa.Column("model_name", sa.String(100), nullable=False),
        sa.Column("status", agent_run_status, nullable=False, server_default="started"),
        sa.Column("prompt_artifact_uri", sa.String(1000), nullable=True),
        sa.Column("response_artifact_uri", sa.String(1000), nullable=True),
        sa.Column("input_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("output_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
    )
    op.create_index("ix_agent_runs_blog_session_id", "agent_runs", ["blog_session_id"])

    # ------------------------------------------------------------------
    # budget_ledger_entries
    # ------------------------------------------------------------------
    op.create_table(
        "budget_ledger_entries",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("end_user_id", sa.BigInteger(), sa.ForeignKey("end_users.id"), nullable=False),
        sa.Column("blog_session_id", sa.BigInteger(), sa.ForeignKey("blog_sessions.id"), nullable=True),
        sa.Column("blog_version_id", sa.BigInteger(), sa.ForeignKey("blog_versions.id"), nullable=True),
        sa.Column("agent_run_id", sa.BigInteger(), sa.ForeignKey("agent_runs.id"), nullable=True),
        sa.Column("entry_type", ledger_entry_type, nullable=False),
        sa.Column("resource_type", ledger_resource_type, nullable=False),
        sa.Column("quantity", sa.Float(), nullable=False),
        sa.Column("unit_cost_usd", sa.Float(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ------------------------------------------------------------------
    # human_review_events
    # ------------------------------------------------------------------
    op.create_table(
        "human_review_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("blog_session_id", sa.BigInteger(), sa.ForeignKey("blog_sessions.id"), nullable=False),
        sa.Column("blog_version_id", sa.BigInteger(), sa.ForeignKey("blog_versions.id"), nullable=False),
        sa.Column("reviewer_user_id", sa.String(255), nullable=False),
        sa.Column("action", human_review_action, nullable=False),
        sa.Column("feedback_text", sa.Text(), nullable=True),
        sa.Column("review_context", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_human_review_events_blog_session_id", "human_review_events", ["blog_session_id"])

    # ------------------------------------------------------------------
    # export_jobs
    # ------------------------------------------------------------------
    op.create_table(
        "export_jobs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("blog_version_id", sa.BigInteger(), sa.ForeignKey("blog_versions.id"), nullable=False),
        sa.Column("format", export_format, nullable=False),
        sa.Column("status", export_status, nullable=False, server_default="pending"),
        sa.Column("artifact_uri", sa.String(1000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    # Drop tables in reverse FK dependency order
    op.drop_table("export_jobs")
    op.drop_table("human_review_events")
    op.drop_table("budget_ledger_entries")
    op.drop_table("agent_runs")
    op.drop_table("blog_versions")
    op.drop_table("blog_sessions")
    op.drop_table("budget_policies")
    op.drop_table("end_users")
    op.drop_table("tenants")
    op.drop_table("service_clients")

    # Drop all enums
    for enum_name in [
        "export_status_enum", "export_format_enum", "human_review_action_enum",
        "agent_run_status_enum", "blog_created_by_enum", "blog_editor_status_enum",
        "blog_version_source_enum", "blog_session_status_enum",
        "ledger_resource_type_enum", "ledger_entry_type_enum", "budget_scope_enum",
        "end_user_status_enum", "tenant_status_enum", "tenant_plan_enum",
        "client_status_enum", "client_mode_enum",
    ]:
        op.execute(f"DROP TYPE IF EXISTS {enum_name}")
