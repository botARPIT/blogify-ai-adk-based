"""Migration 110 — add tracking columns to research_sources.

Revision ID: 110
Revises: 109
Create Date: 2026-05-14

Adds columns needed by the application to store research metadata.
"""

from __future__ import annotations

from alembic import op

revision: str = "110"
down_revision: str | None = "109"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE research_sources
        ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES auth_users(id)
    """)
    op.execute("""
        ALTER TABLE research_sources
        ADD COLUMN IF NOT EXISTS title VARCHAR(500)
    """)
    op.execute("""
        ALTER TABLE research_sources
        ADD COLUMN IF NOT EXISTS content TEXT
    """)
    op.execute("""
        ALTER TABLE research_sources
        ADD COLUMN IF NOT EXISTS score NUMERIC(5,4) NOT NULL DEFAULT 0
    """)
    op.execute("""
        ALTER TABLE research_sources
        ADD COLUMN IF NOT EXISTS topic VARCHAR(500)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_research_sources_user
        ON research_sources (user_id)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_research_sources_user")
    op.execute("ALTER TABLE research_sources DROP COLUMN IF EXISTS user_id")
    op.execute("ALTER TABLE research_sources DROP COLUMN IF EXISTS title")
    op.execute("ALTER TABLE research_sources DROP COLUMN IF EXISTS content")
    op.execute("ALTER TABLE research_sources DROP COLUMN IF EXISTS score")
    op.execute("ALTER TABLE research_sources DROP COLUMN IF EXISTS topic")
