"""Extract lease-based ownership columns to session_leases table.

Revision ID: 015_session_leases
Revises: 014_add_schema_defaults
Create Date: 2026-05-03

1. Create session_leases table with lease columns
2. Migrate existing lease data from blog_sessions
3. Drop lease columns from blog_sessions
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "015_session_leases"
down_revision: Union[str, Sequence[str], None] = "014_add_schema_defaults"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Extract lease columns to separate table."""
    conn = op.get_bind()

    # 1. Create session_leases table
    op.create_table(
        "session_leases",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("blog_session_id", sa.BigInteger(), nullable=False),
        sa.Column("lease_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reap_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("owned_by", sa.String(100), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.ForeignKeyConstraint(["blog_session_id"], ["blog_sessions.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("blog_session_id", name="uq_session_lease"),
    )
    op.create_index("ix_session_leases_blog_session_id", "session_leases", ["blog_session_id"], unique=True)

    # 2. Migrate existing data (only rows that have lease activity)
    conn.execute(
        sa.text("""
            INSERT INTO session_leases 
                (blog_session_id, lease_version, reap_count, owned_by, claimed_at, last_heartbeat_at)
            SELECT 
                id, lease_version, reap_count, owned_by, claimed_at, last_heartbeat_at
            FROM blog_sessions
            WHERE 
                owned_by IS NOT NULL 
                OR lease_version > 0 
                OR reap_count > 0
                OR claimed_at IS NOT NULL 
                OR last_heartbeat_at IS NOT NULL
        """)
    )

    # 3. Drop lease columns from blog_sessions
    op.drop_column("blog_sessions", "lease_version")
    op.drop_column("blog_sessions", "reap_count")
    op.drop_column("blog_sessions", "owned_by")
    op.drop_column("blog_sessions", "claimed_at")
    op.drop_column("blog_sessions", "last_heartbeat_at")


def downgrade() -> None:
    """Reverse lease extraction: restore columns to blog_sessions."""
    conn = op.get_bind()

    # 1. Add lease columns back to blog_sessions
    op.add_column("blog_sessions", sa.Column("lease_version", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("blog_sessions", sa.Column("reap_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("blog_sessions", sa.Column("owned_by", sa.String(100), nullable=True))
    op.add_column("blog_sessions", sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("blog_sessions", sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True))

    # 2. Copy data back from session_leases
    conn.execute(
        sa.text("""
            UPDATE blog_sessions bs
            SET 
                lease_version = COALESCE(sl.lease_version, 0),
                reap_count = COALESCE(sl.reap_count, 0),
                owned_by = sl.owned_by,
                claimed_at = sl.claimed_at,
                last_heartbeat_at = sl.last_heartbeat_at
            FROM session_leases sl
            WHERE sl.blog_session_id = bs.id
        """)
    )

    # 3. Drop session_leases table
    op.drop_index("ix_session_leases_blog_session_id", table_name="session_leases")
    op.drop_table("session_leases")
