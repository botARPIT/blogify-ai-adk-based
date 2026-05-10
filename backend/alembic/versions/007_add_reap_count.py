"""add reap_count for accurate reaping

Revision ID: 007_add_reap_count
Revises: 006_lease_fix
Create Date: 2026-04-28

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '007_add_reap_count'
down_revision: Union[str, Sequence[str], None] = '006_lease_fix'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add reap_count column to track actual reaps separately from lease_version."""
    op.add_column(
        'blog_sessions',
        sa.Column('reap_count', sa.Integer(), nullable=False, server_default='0')
    )


def downgrade() -> None:
    """Remove reap_count column."""
    op.drop_column('blog_sessions', 'reap_count')