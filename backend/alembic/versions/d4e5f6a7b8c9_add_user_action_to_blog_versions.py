"""add user_action to blog_versions

Revision ID: d4e5f6a7b8c9
Revises: c2d4e6f8a9b1
Create Date: 2026-05-30

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, Sequence[str], None] = "c2d4e6f8a9b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "blog_versions",
        sa.Column("user_action", sa.String(length=50), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("blog_versions", "user_action")
