"""Extract lease-based ownership columns to session_leases table.

Revision ID: 015_session_leases
Revises: 001_baseline
Create Date: 2026-05-03
"""

from __future__ import annotations

revision: str = "015_session_leases"
down_revision: str | None = "001_baseline"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
