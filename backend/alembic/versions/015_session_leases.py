"""Stub migration — preserves history for removed migration 015.

Revision ID: 015
Revises: 001_baseline
Create Date: 2026-05-03
"""

from __future__ import annotations

revision: str = "015"
down_revision: str | None = "001_baseline"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
