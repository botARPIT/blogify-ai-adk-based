"""Drop Phase 0 legacy tables (users, blogs, cost_records).

Revision ID: 012_drop_legacy_tables
Revises: 011_add_webhook_secret
Create Date: 2026-05-03

These tables are no longer used by the canonical schema (Phase 1+).
The source of truth for user data is now the Prisma `User` table in the frontend,
and backend canonical tables (end_users, blog_sessions, etc.).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "012_drop_legacy_tables"
down_revision: Union[str, Sequence[str], None] = "011_add_webhook_secret"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Drop legacy tables in dependency order."""

    # 1. Drop cost_records (depends on blogs and users)
    op.drop_index("ix_cost_records_session_id", table_name="cost_records")
    op.drop_table("cost_records")

    # 2. Drop blogs (depends on users)
    op.drop_index("ix_blogs_session_id", table_name="blogs")
    op.drop_table("blogs")

    # 3. Drop users
    op.drop_index("ix_users_user_id", table_name="users")
    op.drop_table("users")


def downgrade() -> None:
    """Recreate legacy tables (exact copy from 000_legacy_schema.py)."""

    # Recreate users table
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("daily_budget_usd", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("daily_blogs_limit", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("total_cost_usd", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("total_blogs_generated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", name="uq_users_user_id"),
    )
    op.create_index("ix_users_user_id", "users", ["user_id"], unique=True)

    # Recreate blogs table
    op.create_table(
        "blogs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(length=255), sa.ForeignKey("users.user_id"), nullable=False),
        sa.Column("session_id", sa.String(length=255), nullable=False),
        sa.Column("topic", sa.String(length=500), nullable=False),
        sa.Column("audience", sa.String(length=255), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("word_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sources_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="in_progress"),
        sa.Column("current_stage", sa.String(length=50), nullable=True),
        sa.Column("stage_data", sa.dialects.postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("total_cost_usd", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("total_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("session_id", name="uq_blogs_session_id"),
    )
    op.create_index("ix_blogs_session_id", "blogs", ["session_id"], unique=True)

    # Recreate cost_records table
    op.create_table(
        "cost_records",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(length=255), sa.ForeignKey("users.user_id"), nullable=False),
        sa.Column("blog_id", sa.Integer(), sa.ForeignKey("blogs.id"), nullable=True),
        sa.Column("session_id", sa.String(length=255), nullable=False),
        sa.Column("agent_name", sa.String(length=100), nullable=False),
        sa.Column("model_name", sa.String(length=100), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_cost_records_session_id", "cost_records", ["session_id"])
