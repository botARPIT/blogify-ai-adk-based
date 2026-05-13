"""Migration 106 — replace budget_ledger_entries with budget_ledger.

Revision ID: 106
Revises: 105
Create Date: 2026-05-14

Replace the multi-tenant budget_ledger_entries table with a simple
budget_ledger table matching the dev schema. Safe to run multiple
times using IF EXISTS / IF NOT EXISTS throughout.
"""

from __future__ import annotations

from alembic import op

revision = "106"
down_revision = "105"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS budget_ledger (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES auth_users(id) ON DELETE CASCADE,
            blog_session_id INTEGER REFERENCES blog_sessions(id) ON DELETE SET NULL,
            agent_run_id INTEGER REFERENCES agent_runs(id) ON DELETE SET NULL,
            entry_type VARCHAR(50) NOT NULL,
            tokens INTEGER NOT NULL DEFAULT 0,
            amount_usd NUMERIC(12,8) NOT NULL DEFAULT 0,
            note VARCHAR(255),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_budget_ledger_user_id
        ON budget_ledger (user_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_budget_ledger_session
        ON budget_ledger (blog_session_id)
    """)

    op.execute("DROP TABLE IF EXISTS budget_ledger_entries CASCADE")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS budget_ledger CASCADE")
