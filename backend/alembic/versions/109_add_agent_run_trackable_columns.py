"""Migration 109 — add tracking columns to agent_runs.

Revision ID: 109
Revises: 108
Create Date: 2026-05-14

Note: agent_runs.stage_name already exists (created by 001_baseline from ORM).
This migration adds the additional tracking columns.
"""

from __future__ import annotations

from alembic import op

revision: str = "109"
down_revision: str | None = "108"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE agent_runs
        ADD COLUMN IF NOT EXISTS agent_name VARCHAR(100)
    """)
    op.execute("""
        ALTER TABLE agent_runs
        ADD COLUMN IF NOT EXISTS model_name VARCHAR(100)
    """)
    op.execute("""
        ALTER TABLE agent_runs
        ADD COLUMN IF NOT EXISTS prompt_tokens INTEGER NOT NULL DEFAULT 0
    """)
    op.execute("""
        ALTER TABLE agent_runs
        ADD COLUMN IF NOT EXISTS completion_tokens INTEGER NOT NULL DEFAULT 0
    """)
    op.execute("""
        ALTER TABLE agent_runs
        ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    """)
    op.execute("""
        ALTER TABLE agent_runs
        ADD CONSTRAINT uq_agent_runs_session_stage
        UNIQUE (blog_session_id, stage_name)
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE agent_runs DROP CONSTRAINT IF EXISTS uq_agent_runs_session_stage")
    op.execute("ALTER TABLE agent_runs DROP COLUMN IF EXISTS agent_name")
    op.execute("ALTER TABLE agent_runs DROP COLUMN IF EXISTS model_name")
    op.execute("ALTER TABLE agent_runs DROP COLUMN IF EXISTS prompt_tokens")
    op.execute("ALTER TABLE agent_runs DROP COLUMN IF EXISTS completion_tokens")
    op.execute("ALTER TABLE agent_runs DROP COLUMN IF EXISTS updated_at")
