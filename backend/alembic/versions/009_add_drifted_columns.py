"""Add drifted columns to blog_sessions that exist in DB but not in migrations.

Revision ID: 009_add_drifted_columns
Revises: 008_saga_orchestration_schema
Create Date: 2026-04-30

This migration is idempotent - checks if columns exist before adding.
Columns being added:
- per_user_blog_number: INTEGER NOT NULL DEFAULT 0 (auto-incrementing counter per user)
- callback_url: VARCHAR(1000) NULL (webhook callback URL)
- callback_enabled: BOOLEAN NOT NULL DEFAULT true (webhook toggle)
- approved_research: JSON NULL (approved research data)
- research_review_deadline: TIMESTAMP WITH TIME ZONE NULL (48h review deadline)
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "009_add_drifted_columns"
down_revision: Union[str, Sequence[str], None] = "008_saga_orchestration_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def column_exists(conn, table: str, column: str) -> bool:
    """Check if a column exists in a table."""
    result = conn.execute(
        sa.text(f"""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = '{table}' AND column_name = '{column}'
        """)
    )
    return result.fetchone() is not None


def upgrade() -> None:
    """Add drifted columns to blog_sessions table (idempotent)."""
    conn = op.get_bind()

    # per_user_blog_number
    if not column_exists(conn, "blog_sessions", "per_user_blog_number"):
        op.add_column(
            "blog_sessions",
            sa.Column("per_user_blog_number", sa.Integer(), nullable=False, server_default="0"),
        )

    # callback_url
    if not column_exists(conn, "blog_sessions", "callback_url"):
        op.add_column(
            "blog_sessions",
            sa.Column("callback_url", sa.String(1000), nullable=True),
        )

    # callback_enabled
    if not column_exists(conn, "blog_sessions", "callback_enabled"):
        op.add_column(
            "blog_sessions",
            sa.Column("callback_enabled", sa.Boolean(), nullable=False, server_default="true"),
        )

    # approved_research
    if not column_exists(conn, "blog_sessions", "approved_research"):
        op.add_column(
            "blog_sessions",
            sa.Column("approved_research", sa.JSON, nullable=True),
        )

    # research_review_deadline
    if not column_exists(conn, "blog_sessions", "research_review_deadline"):
        op.add_column(
            "blog_sessions",
            sa.Column("research_review_deadline", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    """Remove drifted columns from blog_sessions table."""
    op.drop_column("blog_sessions", "research_review_deadline")
    op.drop_column("blog_sessions", "approved_research")
    op.drop_column("blog_sessions", "callback_enabled")
    op.drop_column("blog_sessions", "callback_url")
    op.drop_column("blog_sessions", "per_user_blog_number")