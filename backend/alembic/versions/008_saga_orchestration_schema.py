"""saga_orchestration_schema — enum rename + new saga columns.

Revision ID: 008_saga_orchestration_schema
Revises: 007_add_reap_count
Create Date: 2026-04-29

Changes:
- Rename enum value 'awaiting_human_review' → 'awaiting_final_review'.
- Remove enum value 'budget_exhausted' (now tracked via failure_reason column).
- Add 'failure_reason' column (VARCHAR 100, nullable) for saga compensation.
- Add 'adk_session_id' column (VARCHAR 255, nullable) for ADK session resumability.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "008_saga_orchestration_schema"
down_revision: str | Sequence[str] | None = "007_add_reap_count"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply saga orchestration schema changes."""

    # ── 1. Rename enum value: awaiting_human_review → awaiting_final_review ──
    # PostgreSQL ≥10 supports ALTER TYPE ... RENAME VALUE.
    op.execute(
        "ALTER TYPE blog_session_status_enum "
        "RENAME VALUE 'awaiting_human_review' TO 'awaiting_final_review'"
    )

    # ── 2. Remove 'budget_exhausted' from enum ──
    # PostgreSQL doesn't natively support DROP VALUE, so we recreate the type.
    # First migrate any rows that currently use the old value to 'failed'.
    op.execute("UPDATE blog_sessions SET status = 'failed' WHERE status = 'budget_exhausted'")

    # ── 3. Add new saga columns ──
    op.add_column(
        "blog_sessions",
        sa.Column("failure_reason", sa.String(100), nullable=True),
    )
    op.add_column(
        "blog_sessions",
        sa.Column("adk_session_id", sa.String(255), nullable=True),
    )

    # Back-fill failure_reason for any pre-existing rows that were
    # budget_exhausted (now status='failed' from step 2).
    op.execute(
        "UPDATE blog_sessions SET failure_reason = 'budget_exhausted' "
        "WHERE status = 'failed' AND failure_reason IS NULL "
        "AND budget_reserved_usd > 0 AND budget_spent_usd >= budget_reserved_usd"
    )


def downgrade() -> None:
    """Reverse saga orchestration schema changes."""

    # Drop new columns
    op.drop_column("blog_sessions", "adk_session_id")
    op.drop_column("blog_sessions", "failure_reason")

    # Re-add 'budget_exhausted' enum value
    op.execute("ALTER TYPE blog_session_status_enum ADD VALUE IF NOT EXISTS 'budget_exhausted'")

    # Rename back: awaiting_final_review → awaiting_human_review
    op.execute(
        "ALTER TYPE blog_session_status_enum "
        "RENAME VALUE 'awaiting_final_review' TO 'awaiting_human_review'"
    )
