"""V1 schema - fresh start for blogify-ai-adk.

Revision ID: 100
Revises:
Create Date: 2025-01-01 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "100"
down_revision: str | Sequence[str] | None = "014_add_schema_defaults"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
