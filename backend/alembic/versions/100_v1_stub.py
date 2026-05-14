"""Stub migration — stub for removed migration 100.

Revision ID: 100
Revises: 016
Create Date: 2026-05-07
"""

from __future__ import annotations

revision: str = "100"
down_revision: str | None = "016"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
