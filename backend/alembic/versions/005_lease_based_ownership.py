"""Add lease-based ownership columns to blog_sessions.

Supports DB-authoritative job reaper and split-brain prevention:
- lease_version: monotonically increasing lock version
- owned_by: worker ID holding the lease
- claimed_at: when the worker claimed the job
- last_heartbeat_at: last proof-of-life from the worker
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "005_lease_based_ownership"
down_revision = "004_service_client_budget_policy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "blog_sessions",
        sa.Column("lease_version", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "blog_sessions",
        sa.Column("owned_by", sa.String(100), nullable=True),
    )
    op.add_column(
        "blog_sessions",
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "blog_sessions",
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Index for reaper queries: find stale processing jobs quickly
    op.create_index(
        "ix_blog_sessions_reaper",
        "blog_sessions",
        ["status", "last_heartbeat_at"],
        postgresql_where=sa.text("status = 'processing'"),
    )


def downgrade() -> None:
    op.drop_index("ix_blog_sessions_reaper", table_name="blog_sessions")
    op.drop_column("blog_sessions", "last_heartbeat_at")
    op.drop_column("blog_sessions", "claimed_at")
    op.drop_column("blog_sessions", "owned_by")
    op.drop_column("blog_sessions", "lease_version")
