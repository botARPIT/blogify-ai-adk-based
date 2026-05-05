"""Add webhook_secret column to service_clients.

Revision ID: 011_add_webhook_secret
Revises: 010_add_budget_ledger_columns
Create Date: 2026-04-30

This migration is idempotent - checks if column exists before adding.

Column being added:
- webhook_secret: VARCHAR(255) NULL (webhook authentication secret)
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "011_add_webhook_secret"
down_revision: Union[str, Sequence[str], None] = "010_add_budget_ledger_columns"
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
    """Add webhook_secret column to service_clients table (idempotent)."""
    conn = op.get_bind()

    if not column_exists(conn, "service_clients", "webhook_secret"):
        op.add_column(
            "service_clients",
            sa.Column("webhook_secret", sa.String(255), nullable=True),
        )


def downgrade() -> None:
    """Remove webhook_secret column from service_clients table."""
    op.drop_column("service_clients", "webhook_secret")