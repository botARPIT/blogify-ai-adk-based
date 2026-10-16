"""Track the current UTC-day blog quota and set the default to five.

Revision ID: c3d4e5f6a7b8
Revises: a7b8c9d0e1f2
Create Date: 2026-10-13

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c3d4e5f6a7b8"
down_revision: str | None = "a7b8c9d0e1f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "user_blog_quotas",
        sa.Column("usage_date", sa.Date(), nullable=True),
    )
    # The old counter was not connected to generation requests. Start the new
    # calendar-day accounting cleanly when this migration is applied.
    op.execute(
        "UPDATE user_blog_quotas "
        "SET blogs_used = 0, blogs_limit = 5, usage_date = CURRENT_DATE"
    )
    op.alter_column(
        "user_blog_quotas",
        "usage_date",
        existing_type=sa.Date(),
        nullable=False,
        server_default=sa.text("CURRENT_DATE"),
    )
    op.alter_column(
        "user_blog_quotas",
        "blogs_limit",
        existing_type=sa.Integer(),
        server_default="5",
    )


def downgrade() -> None:
    op.alter_column(
        "user_blog_quotas",
        "blogs_limit",
        existing_type=sa.Integer(),
        server_default="10",
    )
    op.drop_column("user_blog_quotas", "usage_date")
