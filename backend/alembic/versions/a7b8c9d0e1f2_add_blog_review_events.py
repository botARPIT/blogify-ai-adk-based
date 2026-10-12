"""Add persisted human review history.

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-10-13

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a7b8c9d0e1f2"
down_revision: str | None = "f6a7b8c9d0e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "blog_review_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("blog_session_id", sa.Integer(), nullable=False),
        sa.Column("blog_version_id", sa.Integer(), nullable=True),
        sa.Column("reviewer_user_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=50), nullable=False),
        sa.Column("feedback_text", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.ForeignKeyConstraint(
            ["blog_session_id"], ["blog_sessions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["blog_version_id"], ["blog_versions.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["reviewer_user_id"], ["auth_users.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_blog_review_events_session_created",
        "blog_review_events",
        ["blog_session_id", "created_at"],
    )
    op.create_index(
        "ix_blog_review_events_version", "blog_review_events", ["blog_version_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_blog_review_events_version", table_name="blog_review_events")
    op.drop_index("ix_blog_review_events_session_created", table_name="blog_review_events")
    op.drop_table("blog_review_events")
