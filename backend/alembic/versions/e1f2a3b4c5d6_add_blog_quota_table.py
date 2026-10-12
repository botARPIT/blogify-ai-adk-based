"""add blog quota table

Revision ID: e1f2a3b4c5d6
Revises: 367700a374ec
Create Date: 2026-07-05

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e1f2a3b4c5d6"
down_revision: Union[str, None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_blog_quotas",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("blogs_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("blogs_limit", sa.Integer(), nullable=False, server_default="10"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["auth_users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_user_blog_quotas_user_id"),
    )
    op.create_index("ix_user_blog_quotas_user_id", "user_blog_quotas", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_user_blog_quotas_user_id", table_name="user_blog_quotas")
    op.drop_table("user_blog_quotas")
