"""Drop lease columns from blog_sessions table.

Revision ID: 103
Revises: 102
Create Date: 2026-05-08

Removes lease tracking columns from blog_sessions table as lease ownership
has been moved to the separate session_leases table.
"""

from collections.abc import Sequence

from sqlalchemy import text

from alembic import op

revision: str = "103"
down_revision: str | Sequence[str] | None = "102"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()

    columns_to_drop = ["lease_owner", "lease_expires_at", "lease_version", "last_heartbeat_at"]

    for col in columns_to_drop:
        result = conn.execute(
            text(f"""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'blog_sessions' AND column_name = '{col}'
        """)
        )

        if result.fetchone():
            # Check if index exists
            index_result = conn.execute(
                text("""
                SELECT indexname 
                FROM pg_indexes 
                WHERE tablename = 'blog_sessions' AND indexname = 'ix_blog_sessions_lease_expires'
            """)
            )
            if index_result.fetchone() and col == "lease_expires_at":
                op.drop_index("ix_blog_sessions_lease_expires", table_name="blog_sessions")

            op.drop_column("blog_sessions", col)


def downgrade() -> None:
    pass
