"""Migration 108 — add tracking columns to session_reservations.

Revision ID: 108
Revises: 107
Create Date: 2026-05-14

Adds columns needed by BudgetService to track per-session reservation state.
"""

from __future__ import annotations

from alembic import op

revision: str = "108"
down_revision: str | None = "107"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE session_reservations
        ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES auth_users(id)
    """)
    op.execute("""
        ALTER TABLE session_reservations
        ADD COLUMN IF NOT EXISTS actual_usd NUMERIC(12,8) NOT NULL DEFAULT 0
    """)
    op.execute("""
        ALTER TABLE session_reservations
        ADD COLUMN IF NOT EXISTS actual_tokens INTEGER NOT NULL DEFAULT 0
    """)
    op.execute("""
        ALTER TABLE session_reservations
        ADD COLUMN IF NOT EXISTS status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE'
    """)
    op.execute("""
        ALTER TABLE session_reservations
        ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_session_reservations_user
        ON session_reservations (user_id)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_session_reservations_user")
    op.execute("ALTER TABLE session_reservations DROP COLUMN IF EXISTS user_id")
    op.execute("ALTER TABLE session_reservations DROP COLUMN IF EXISTS actual_usd")
    op.execute("ALTER TABLE session_reservations DROP COLUMN IF EXISTS actual_tokens")
    op.execute("ALTER TABLE session_reservations DROP COLUMN IF EXISTS status")
    op.execute("ALTER TABLE session_reservations DROP COLUMN IF EXISTS updated_at")
