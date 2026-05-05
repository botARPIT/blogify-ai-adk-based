"""Add drifted columns to budget_ledger_entries and create budget_reservations table.

Revision ID: 010_add_budget_ledger_columns
Revises: 009_add_drifted_columns
Create Date: 2026-04-30

This migration is idempotent - checks if columns/tables exist before adding.

Columns being added to budget_ledger_entries:
- reservation_id: BIGINT NULL (FK to budget_reservations)
- window_type: ENUM NOT NULL DEFAULT 'daily' (daily/weekly/monthly)
- window_start: TIMESTAMP WITH TIME ZONE NULL (budget window start)

Also creates budget_reservations table if not exists.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "010_add_budget_ledger_columns"
down_revision: Union[str, Sequence[str], None] = "009_add_drifted_columns"
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


def table_exists(conn, table: str) -> bool:
    """Check if a table exists."""
    result = conn.execute(
        sa.text(f"""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_name = '{table}' AND table_schema = 'public'
        """)
    )
    return result.fetchone() is not None


def enum_exists(conn, enum_name: str) -> bool:
    """Check if an enum type exists."""
    result = conn.execute(
        sa.text(f"""
            SELECT typname FROM pg_type 
            WHERE typname = '{enum_name}'
        """)
    )
    return result.fetchone() is not None


def upgrade() -> None:
    """Add drifted columns to budget_ledger_entries and create budget_reservations."""
    conn = op.get_bind()

    # Create budget_window_type_enum if not exists
    if not enum_exists(conn, "budget_window_type_enum"):
        budget_window_type = postgresql.ENUM(
            "daily", "weekly", "monthly", name="budget_window_type_enum", create_type=False
        )
        budget_window_type.create(op.get_bind(), checkfirst=True)
        conn.execute(sa.text("ALTER TYPE budget_window_type_enum ADD VALUE IF NOT EXISTS 'daily'"))
        conn.execute(sa.text("ALTER TYPE budget_window_type_enum ADD VALUE IF NOT EXISTS 'weekly'"))
        conn.execute(sa.text("ALTER TYPE budget_window_type_enum ADD VALUE IF NOT EXISTS 'monthly'"))

    # Create budget_reservations table if not exists
    if not table_exists(conn, "budget_reservations"):
        op.create_table(
            "budget_reservations",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
            sa.Column("end_user_id", sa.BigInteger(), sa.ForeignKey("end_users.id"), nullable=False),
            sa.Column("blog_session_id", sa.BigInteger(), sa.ForeignKey("blog_sessions.id"), nullable=True),
            sa.Column("resource_type", sa.String(50), nullable=False),
            sa.Column("quantity", sa.Float(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_budget_reservations_tenant_end_user", "budget_reservations", ["tenant_id", "end_user_id"])
        op.create_index("ix_budget_reservations_blog_session", "budget_reservations", ["blog_session_id"])

    # Add reservation_id to budget_ledger_entries
    if not column_exists(conn, "budget_ledger_entries", "reservation_id"):
        op.add_column(
            "budget_ledger_entries",
            sa.Column("reservation_id", sa.BigInteger(), sa.ForeignKey("budget_reservations.id"), nullable=True),
        )

    # Add window_type to budget_ledger_entries
    if not column_exists(conn, "budget_ledger_entries", "window_type"):
        op.add_column(
            "budget_ledger_entries",
            sa.Column("window_type", sa.Enum("daily", "weekly", "monthly", name="budget_window_type_enum"), nullable=False, server_default="daily"),
        )

    # Add window_start to budget_ledger_entries
    if not column_exists(conn, "budget_ledger_entries", "window_start"):
        op.add_column(
            "budget_ledger_entries",
            sa.Column("window_start", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    """Remove drifted columns from budget_ledger_entries and drop budget_reservations."""
    op.drop_column("budget_ledger_entries", "window_start")
    op.drop_column("budget_ledger_entries", "window_type")
    op.drop_column("budget_ledger_entries", "reservation_id")
    
    op.drop_index("ix_budget_reservations_blog_session", table_name="budget_reservations")
    op.drop_index("ix_budget_reservations_tenant_end_user", table_name="budget_reservations")
    op.drop_table("budget_reservations")
    
    op.execute("DROP TYPE IF EXISTS budget_window_type_enum")