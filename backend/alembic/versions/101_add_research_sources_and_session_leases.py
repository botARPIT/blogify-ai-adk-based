"""Migration 101 — add user_id column to agent_runs.

Revision ID: 101
Revises: 015_session_leases
Create Date: 2026-05-08

Adds user_id foreign key to agent_runs for ownership tracking.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "101"
down_revision: str | Sequence[str] | None = "100"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE agent_runs
        ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES auth_users(id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_agent_runs_user
        ON agent_runs (user_id)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_agent_runs_user")
    op.execute("ALTER TABLE agent_runs DROP COLUMN IF EXISTS user_id")
