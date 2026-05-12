"""Extract lease-based ownership columns to session_leases table.

Revision ID: 015_session_leases
Revises: 100
Create Date: 2026-05-03

Note: This migration is now a no-op since 100_v1_schema already includes
the session_leases table. Kept for historical consistency.
"""

from collections.abc import Sequence

revision: str = "015_session_leases"
down_revision: str | Sequence[str] | None = "100"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """No-op: session_leases table already created in migration 100_v1_schema."""
    pass


def downgrade() -> None:
    """No-op: cannot downgrade as 100 already created the table."""
    pass
