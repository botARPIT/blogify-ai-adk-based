"""Add budget_reservations status, blog_sessions error_message, and set default.

Revision ID: 014_add_schema_defaults
Revises: 013_fix_schema_gaps
Create Date: 2026-05-03

2. Add status column to budget_reservations with check constraint, backfill, and partial index
3. Add error_message column to blog_sessions
4. Change blog_sessions default status to 'awaiting_budget_resolution'
"""

from typing import Sequence, Union
import logging

import sqlalchemy as sa
from alembic import op

revision: str = "014_add_schema_defaults"
down_revision: Union[str, Sequence[str], None] = "013_fix_schema_gaps"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

logger = logging.getLogger(__name__)


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
    """Apply schema fixes idempotently."""
    conn = op.get_bind()

    # 2. Add status to budget_reservations
    if not column_exists(conn, "budget_reservations", "status"):
        # Add column with default
        op.add_column(
            "budget_reservations",
            sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        )
        # Add check constraint
        op.create_check_constraint(
            "chk_budget_res_status",
            "budget_reservations",
            sa.text("status IN ('active', 'committed', 'released', 'expired')"),
        )
        # Backfill expired rows
        conn.execute(
            sa.text("""
                UPDATE budget_reservations 
                SET status = 'released' 
                WHERE expires_at IS NOT NULL AND expires_at < NOW()
            """)
        )
        # Create partial index for active reservations
        op.create_index(
            "ix_budget_reservations_active",
            "budget_reservations",
            ["end_user_id", "status"],
            postgresql_where=sa.text("status = 'active'"),
        )

    # 3. Add error_message to blog_sessions
    if not column_exists(conn, "blog_sessions", "error_message"):
        op.add_column(
            "blog_sessions",
            sa.Column("error_message", sa.Text(), nullable=True),
        )

    # 4. Change blog_sessions default status
    conn.execute(
        sa.text("ALTER TABLE blog_sessions ALTER COLUMN status SET DEFAULT 'awaiting_budget_resolution'")
    )


def downgrade() -> None:
    """Reverse schema fixes where possible."""
    conn = op.get_bind()

    # 4. Reverse: Restore original default status ('queued')
    conn.execute(
        sa.text("ALTER TABLE blog_sessions ALTER COLUMN status SET DEFAULT 'queued'")
    )

    # 3. Reverse: Drop error_message column
    op.drop_column("blog_sessions", "error_message")

    # 2. Reverse: Drop index, constraint, and status column
    op.drop_index("ix_budget_reservations_active", table_name="budget_reservations")
    op.drop_constraint("chk_budget_res_status", "budget_reservations", type_="check")
    op.drop_column("budget_reservations", "status")
