"""Add missing enum values to blog_session_status_enum.

Revision ID: 013_fix_schema_gaps
Revises: 012_drop_legacy_tables
Create Date: 2026-05-03

1. Add missing enum values to blog_session_status_enum:
   - awaiting_budget_resolution
   - awaiting_human_review
   - awaiting_research_review
"""

import logging
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "013_fix_schema_gaps"
down_revision: str | Sequence[str] | None = "012_drop_legacy_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

logger = logging.getLogger(__name__)


def upgrade() -> None:
    """Add missing enum values idempotently."""

    # ALTER TYPE cannot run inside a transaction; use autocommit_block
    with op.get_context().autocommit_block():
        op.execute(
            sa.text(
                "ALTER TYPE blog_session_status_enum ADD VALUE IF NOT EXISTS 'awaiting_budget_resolution'"
            )
        )
        op.execute(
            sa.text(
                "ALTER TYPE blog_session_status_enum ADD VALUE IF NOT EXISTS 'awaiting_human_review'"
            )
        )
        op.execute(
            sa.text(
                "ALTER TYPE blog_session_status_enum ADD VALUE IF NOT EXISTS 'awaiting_research_review'"
            )
        )


def downgrade() -> None:
    """Reverse schema fixes where possible."""
    # Cannot remove enum values from PostgreSQL enum; log warning
    logger.warning(
        "Cannot remove enum values from blog_session_status_enum. "
        "Manual cleanup required if needed."
    )
