"""fix session_reservations created_at default and cleanup invalid indexes

Revision ID: 367700a374ec
Revises: b0d04a975349
Create Date: 2026-05-15

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "367700a374ec"
down_revision: Union[str, Sequence[str], None] = "b0d04a975349"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add DB-level default for created_at so existing rows and future inserts
    # that omit the column never produce a NOT NULL violation.
    op.alter_column(
        "session_reservations",
        "created_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    )

    # Defensive cleanup in case these indexes somehow exist
    # (they should not exist based on the original migration)
    op.execute("DROP INDEX IF EXISTS ix_session_reservations_user")
    op.execute("DROP INDEX IF EXISTS ix_research_sources_user")


def downgrade() -> None:
    # Remove DB-level default
    op.alter_column(
        "session_reservations",
        "created_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
        server_default=None,
    )

    # Intentionally DO NOT recreate the invalid indexes.
    # They never belonged in the schema.
