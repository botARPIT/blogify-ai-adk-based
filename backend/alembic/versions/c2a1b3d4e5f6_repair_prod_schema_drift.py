"""Repair production schema drift — align agent_runs and session_leases with ORM.

Production DB was built from a pre-consolidation migration chain that used
different column names.  This migration is idempotent: every ALTER uses
IF EXISTS / IF NOT EXISTS guards so re-running against an already-correct DB
(e.g. local dev) is a no-op.

Changes
-------
agent_runs:
  • RENAME  stage       → stage_name   (also widen VARCHAR 80→100)
  • RENAME  token_count → total_tokens

session_leases (prod table has old shape from an early migration):
  • RENAME  worker_id   → lease_owner  (set NOT NULL, existing NULLs → '')
  • RENAME  acquired_at → started_at
  • RENAME  expires_at  → lease_expires_at
  • RENAME  released_at → ended_at
  • ADD     lease_version     INTEGER NOT NULL DEFAULT 1
  • ADD     last_heartbeat_at TIMESTAMPTZ NULL
  • ADD     release_reason    VARCHAR(50)  NULL
  • Rebuild indexes with ORM-expected names

Revision ID: c2a1b3d4e5f6
Revises: b0d04a975349
Create Date: 2026-05-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "c2a1b3d4e5f6"
down_revision: str | None = "b0d04a975349"
branch_labels: str | None = None
depends_on: str | None = None


def _column_exists(table: str, column: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = :t AND column_name = :c"
        ),
        {"t": table, "c": column},
    )
    return result.fetchone() is not None


def _index_exists(index: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(
        sa.text("SELECT 1 FROM pg_indexes WHERE indexname = :i"),
        {"i": index},
    )
    return result.fetchone() is not None


# ─────────────────────────────────────────────────────────────────────────────
# UPGRADE
# ─────────────────────────────────────────────────────────────────────────────
def upgrade() -> None:
    # ── agent_runs ────────────────────────────────────────────────────────────

    # 1. stage → stage_name  (widen VARCHAR 80 → 100)
    if _column_exists("agent_runs", "stage") and not _column_exists(
        "agent_runs", "stage_name"
    ):
        op.execute("ALTER TABLE agent_runs RENAME COLUMN stage TO stage_name")
    if _column_exists("agent_runs", "stage_name"):
        op.execute(
            "ALTER TABLE agent_runs ALTER COLUMN stage_name TYPE VARCHAR(100)"
        )
        op.execute(
            "UPDATE agent_runs SET stage_name = 'unknown' WHERE stage_name IS NULL"
        )
        op.execute(
            "ALTER TABLE agent_runs ALTER COLUMN stage_name SET NOT NULL"
        )

    # 2. token_count → total_tokens
    if _column_exists("agent_runs", "token_count") and not _column_exists(
        "agent_runs", "total_tokens"
    ):
        op.execute(
            "ALTER TABLE agent_runs RENAME COLUMN token_count TO total_tokens"
        )
    if _column_exists("agent_runs", "total_tokens"):
        op.execute(
            "UPDATE agent_runs SET total_tokens = 0 WHERE total_tokens IS NULL"
        )
        op.execute(
            "ALTER TABLE agent_runs ALTER COLUMN total_tokens SET NOT NULL"
        )

    # 3. Ensure cost_usd / status NOT NULL
    if _column_exists("agent_runs", "cost_usd"):
        op.execute("UPDATE agent_runs SET cost_usd = 0 WHERE cost_usd IS NULL")
        op.execute("ALTER TABLE agent_runs ALTER COLUMN cost_usd SET NOT NULL")
    if _column_exists("agent_runs", "status"):
        op.execute(
            "UPDATE agent_runs SET status = 'UNKNOWN' WHERE status IS NULL"
        )
        op.execute("ALTER TABLE agent_runs ALTER COLUMN status SET NOT NULL")

    # ── session_leases ────────────────────────────────────────────────────────

    # 4. worker_id → lease_owner
    if _column_exists("session_leases", "worker_id") and not _column_exists(
        "session_leases", "lease_owner"
    ):
        op.execute(
            "UPDATE session_leases SET worker_id = '' WHERE worker_id IS NULL"
        )
        op.execute(
            "ALTER TABLE session_leases RENAME COLUMN worker_id TO lease_owner"
        )
    if _column_exists("session_leases", "lease_owner"):
        op.execute(
            "UPDATE session_leases SET lease_owner = '' WHERE lease_owner IS NULL"
        )
        op.execute(
            "ALTER TABLE session_leases ALTER COLUMN lease_owner SET NOT NULL"
        )

    # 5. acquired_at → started_at
    if _column_exists("session_leases", "acquired_at") and not _column_exists(
        "session_leases", "started_at"
    ):
        op.execute(
            "ALTER TABLE session_leases RENAME COLUMN acquired_at TO started_at"
        )

    # 6. expires_at → lease_expires_at
    if _column_exists("session_leases", "expires_at") and not _column_exists(
        "session_leases", "lease_expires_at"
    ):
        op.execute(
            "ALTER TABLE session_leases RENAME COLUMN expires_at TO lease_expires_at"
        )

    # 7. released_at → ended_at
    if _column_exists("session_leases", "released_at") and not _column_exists(
        "session_leases", "ended_at"
    ):
        op.execute(
            "ALTER TABLE session_leases RENAME COLUMN released_at TO ended_at"
        )

    # 8. ADD missing columns
    if not _column_exists("session_leases", "lease_version"):
        op.execute(
            "ALTER TABLE session_leases "
            "ADD COLUMN lease_version INTEGER NOT NULL DEFAULT 1"
        )
    if not _column_exists("session_leases", "last_heartbeat_at"):
        op.execute(
            "ALTER TABLE session_leases "
            "ADD COLUMN last_heartbeat_at TIMESTAMPTZ NULL"
        )
    if not _column_exists("session_leases", "release_reason"):
        op.execute(
            "ALTER TABLE session_leases "
            "ADD COLUMN release_reason VARCHAR(50) NULL"
        )

    # 9. Rebuild indexes — drop old names, create ORM-expected names
    if _index_exists("fk_session_leases_session") and not _index_exists(
        "ix_session_leases_session"
    ):
        op.execute("DROP INDEX IF EXISTS fk_session_leases_session")
        op.execute(
            "CREATE INDEX ix_session_leases_session "
            "ON session_leases (blog_session_id)"
        )
    if not _index_exists("ix_session_leases_owner"):
        op.execute(
            "CREATE INDEX ix_session_leases_owner ON session_leases (lease_owner)"
        )
    if not _index_exists("ix_session_leases_ended"):
        op.execute(
            "CREATE INDEX ix_session_leases_ended ON session_leases (ended_at)"
        )
    if not _index_exists("ix_session_leases_started"):
        op.execute(
            "CREATE INDEX ix_session_leases_started ON session_leases (started_at)"
        )

    # 10. research_sources — old index name → ORM-expected name
    if _index_exists("fk_research_sources_session") and not _index_exists(
        "ix_research_sources_session"
    ):
        op.execute("DROP INDEX IF EXISTS fk_research_sources_session")
        op.execute(
            "CREATE INDEX ix_research_sources_session "
            "ON research_sources (blog_session_id)"
        )


# ─────────────────────────────────────────────────────────────────────────────
# DOWNGRADE  (best-effort; column renames cannot be reversed if data changed)
# ─────────────────────────────────────────────────────────────────────────────
def downgrade() -> None:
    # agent_runs
    if _column_exists("agent_runs", "stage_name") and not _column_exists(
        "agent_runs", "stage"
    ):
        op.execute("ALTER TABLE agent_runs RENAME COLUMN stage_name TO stage")
        op.execute("ALTER TABLE agent_runs ALTER COLUMN stage TYPE VARCHAR(80)")
    if _column_exists("agent_runs", "total_tokens") and not _column_exists(
        "agent_runs", "token_count"
    ):
        op.execute(
            "ALTER TABLE agent_runs RENAME COLUMN total_tokens TO token_count"
        )

    # session_leases
    if _column_exists("session_leases", "lease_owner") and not _column_exists(
        "session_leases", "worker_id"
    ):
        op.execute(
            "ALTER TABLE session_leases RENAME COLUMN lease_owner TO worker_id"
        )
    if _column_exists("session_leases", "started_at") and not _column_exists(
        "session_leases", "acquired_at"
    ):
        op.execute(
            "ALTER TABLE session_leases RENAME COLUMN started_at TO acquired_at"
        )
    if _column_exists("session_leases", "lease_expires_at") and not _column_exists(
        "session_leases", "expires_at"
    ):
        op.execute(
            "ALTER TABLE session_leases RENAME COLUMN lease_expires_at TO expires_at"
        )
    if _column_exists("session_leases", "ended_at") and not _column_exists(
        "session_leases", "released_at"
    ):
        op.execute(
            "ALTER TABLE session_leases RENAME COLUMN ended_at TO released_at"
        )
    op.execute("ALTER TABLE session_leases DROP COLUMN IF EXISTS lease_version")
    op.execute("ALTER TABLE session_leases DROP COLUMN IF EXISTS last_heartbeat_at")
    op.execute("ALTER TABLE session_leases DROP COLUMN IF EXISTS release_reason")
