"""add blog_versions table and active_blog_version_id

Revision ID: c2d4e6f8a9b1
Revises: a1b2c3d4e5f6
Create Date: 2026-05-30

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c2d4e6f8a9b1"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "blog_versions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("blog_session_id", sa.Integer(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("job_phase", sa.String(length=50), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("outline_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("approved_outline", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("research_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("draft_content", sa.Text(), nullable=True),
        sa.Column("final_content", sa.Text(), nullable=True),
        sa.Column("editor_review", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("feedback_text", sa.Text(), nullable=True),
        sa.Column("adk_session_id", sa.String(length=255), nullable=True),
        sa.Column("invocation_id", sa.String(length=255), nullable=True),
        sa.Column("confirmation_request_id", sa.String(length=255), nullable=True),
        sa.Column("state_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_from", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["blog_session_id"], ["blog_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "blog_session_id",
            "version_number",
            name="uq_blog_versions_session_version",
        ),
    )
    op.create_index("ix_blog_versions_session", "blog_versions", ["blog_session_id"], unique=False)
    op.create_index("ix_blog_versions_status", "blog_versions", ["status"], unique=False)

    op.add_column(
        "blog_sessions",
        sa.Column("active_blog_version_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_blog_sessions_active_blog_version_id",
        "blog_sessions",
        "blog_versions",
        ["active_blog_version_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_blog_sessions_active_blog_version_id", "blog_sessions", type_="foreignkey")
    op.drop_column("blog_sessions", "active_blog_version_id")
    op.drop_index("ix_blog_versions_status", table_name="blog_versions")
    op.drop_index("ix_blog_versions_session", table_name="blog_versions")
    op.drop_table("blog_versions")
