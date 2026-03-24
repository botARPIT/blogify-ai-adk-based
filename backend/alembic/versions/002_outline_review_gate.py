"""Add outline review gate fields to canonical blog sessions."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "002_outline_review_gate"
down_revision = "001_canonical_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TYPE blog_session_status_enum "
        "ADD VALUE IF NOT EXISTS 'awaiting_outline_review'"
    )
    op.add_column(
        "blog_sessions",
        sa.Column("outline_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "blog_sessions",
        sa.Column("outline_feedback", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("blog_sessions", "outline_feedback")
    op.drop_column("blog_sessions", "outline_data")
