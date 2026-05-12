"""Drop user_id column from agent_runs table if it exists.

Revision ID: 102
Revises: 101
Create Date: 2026-05-08

Removes user_id column from agent_runs table as it was incorrectly added.
"""

from collections.abc import Sequence

from sqlalchemy import text

from alembic import op

revision: str = "102"
down_revision: str | Sequence[str] | None = "101"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()

    # Check if column exists before trying to drop
    result = conn.execute(
        text("""
        SELECT column_name 
        FROM information_schema.columns 
        WHERE table_name = 'agent_runs' AND column_name = 'user_id'
    """)
    )

    if result.fetchone():
        # Check if index exists before dropping
        index_result = conn.execute(
            text("""
            SELECT indexname 
            FROM pg_indexes 
            WHERE tablename = 'agent_runs' AND indexname = 'ix_agent_runs_user_id'
        """)
        )
        if index_result.fetchone():
            op.drop_index("ix_agent_runs_user_id", table_name="agent_runs")

        # Check if foreign key exists before dropping
        fk_result = conn.execute(
            text("""
            SELECT constraint_name 
            FROM information_schema.table_constraints 
            WHERE table_name = 'agent_runs' AND constraint_name = 'fk_agent_runs_user_id'
        """)
        )
        if fk_result.fetchone():
            op.drop_constraint("fk_agent_runs_user_id", table_name="agent_runs", type_="foreignkey")

        op.drop_column("agent_runs", "user_id")


def downgrade() -> None:
    pass
