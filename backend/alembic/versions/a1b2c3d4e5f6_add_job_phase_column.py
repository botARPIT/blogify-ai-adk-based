"""add job_phase column to blog_sessions

Revision ID: a1b2c3d4e5f6
Revises: 367700a374ec
Create Date: 2026-05-30

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "367700a374ec"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "blog_sessions",
        sa.Column("job_phase", sa.String(50), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("blog_sessions", "job_phase")
