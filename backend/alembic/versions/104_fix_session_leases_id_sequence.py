"""Fix missing auto-increment sequence on session_leases.id.

Revision ID: 104
Revises: 103
Create Date: 2026-05-08

Root cause: migrations 100 and 101 created session_leases with
  sa.Column('id', sa.Integer(), autoincrement=True, nullable=False)
but WITHOUT a sa.PrimaryKeyConstraint('id') call, so Alembic never
created the backing SEQUENCE / SERIAL default. The column is a plain
INTEGER NOT NULL with no DEFAULT, so every INSERT returns NULL for id
and triggers a NOT NULL violation.

Fix: create the sequence, attach it as the column default, and seed it
above the current MAX(id) so existing rows are unaffected.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "104"
down_revision: str | Sequence[str] | None = "103"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Create the sequence
    op.execute("CREATE SEQUENCE IF NOT EXISTS session_leases_id_seq")

    # Attach it as the DEFAULT for the id column
    op.execute(
        "ALTER TABLE session_leases ALTER COLUMN id SET DEFAULT nextval('session_leases_id_seq')"
    )

    # Mark the sequence as owned by the column so it is dropped with the table
    op.execute("ALTER SEQUENCE session_leases_id_seq OWNED BY session_leases.id")

    # Seed the sequence above the highest existing id (or start at 1 if empty)
    op.execute(
        "SELECT setval('session_leases_id_seq', "
        "COALESCE((SELECT MAX(id) FROM session_leases), 0) + 1, false)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE session_leases ALTER COLUMN id DROP DEFAULT")
    op.execute("DROP SEQUENCE IF EXISTS session_leases_id_seq")
