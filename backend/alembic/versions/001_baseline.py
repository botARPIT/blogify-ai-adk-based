"""Baseline schema — single source of truth from dev.

Revision ID: 001_baseline
Revises:
Create Date: 2026-05-14

Loads the complete dev schema from 000_baseline_schema.sql.
This migration creates all tables, indexes, sequences, and constraints
as defined in the current local dev database. Downgrade not supported —
restore from snapshot to roll back.
"""

from __future__ import annotations

from pathlib import Path

from alembic import op

revision: str = "001_baseline"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    sql_file = Path(__file__).parent / "000_baseline_schema.sql"
    op.execute(sql_file.read_text())


def downgrade() -> None:
    raise NotImplementedError(
        "Cannot downgrade baseline migration — restore from a database snapshot"
    )
