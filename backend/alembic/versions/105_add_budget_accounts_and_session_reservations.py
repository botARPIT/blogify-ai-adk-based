"""Migration 105 — add budget_accounts and session_reservations tables.

Revision ID: 105
Revises: 104
Create Date: 2026-05-09

Changes:
  1. Create budget_accounts (one row per user — authoritative balance).
  2. Create session_reservations (per-session reservation tracking).
  3. Backfill budget_accounts from existing budget_ledger data so existing
     users have a correct starting balance (ledger sum at migration time).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "105"
down_revision: str | Sequence[str] | None = "104"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------ #
    # 1. budget_accounts                                                   #
    # ------------------------------------------------------------------ #
    op.create_table(
        "budget_accounts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("balance_usd", sa.Numeric(12, 8), nullable=False, server_default="0"),
        sa.Column("reserved_usd", sa.Numeric(12, 8), nullable=False, server_default="0"),
        sa.Column("total_granted_usd", sa.Numeric(12, 8), nullable=False, server_default="0"),
        sa.Column("total_spent_usd", sa.Numeric(12, 8), nullable=False, server_default="0"),
        sa.Column(
            "last_updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["auth_users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_budget_accounts_user_id"),
    )
    op.create_index("ix_budget_accounts_user_id", "budget_accounts", ["user_id"])

    # ------------------------------------------------------------------ #
    # 2. session_reservations                                              #
    # ------------------------------------------------------------------ #
    op.create_table(
        "session_reservations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("blog_session_id", sa.Integer(), nullable=False),
        sa.Column("reserved_usd", sa.Numeric(12, 8), nullable=False),
        sa.Column("reserved_tokens", sa.Integer(), nullable=False),
        sa.Column("actual_usd", sa.Numeric(12, 8), nullable=False, server_default="0"),
        sa.Column("actual_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="ACTIVE",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["auth_users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["blog_session_id"], ["blog_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("blog_session_id", name="uq_session_reservations_session"),
    )
    op.create_index("ix_session_reservations_user", "session_reservations", ["user_id"])
    op.create_index("ix_session_reservations_session", "session_reservations", ["blog_session_id"])

    # ------------------------------------------------------------------ #
    # 3. Backfill budget_accounts from ledger sums                        #
    #    balance_usd  = sum of all GRANT entries (positive, credit)        #
    #    total_spent  = abs(sum of all COMMIT entries)                     #
    #    total_granted = same as balance before spending                   #
    # ------------------------------------------------------------------ #
    op.execute(
        sa.text(
            """
            INSERT INTO budget_accounts (
                user_id,
                balance_usd,
                reserved_usd,
                total_granted_usd,
                total_spent_usd,
                created_at,
                last_updated_at
            )
            SELECT
                user_id,
                -- net balance = sum of all entries (GRANT positive, COMMIT/RESERVE negative)
                COALESCE(SUM(amount_usd), 0)  AS balance_usd,
                -- reserved_usd: sum of active RESERVE entries not yet released/committed
                -- Approximation at migration time: assume 0 (clean slate for in-flight sessions)
                0                              AS reserved_usd,
                -- total granted = sum of GRANT entries only
                COALESCE(SUM(CASE WHEN entry_type = 'GRANT' THEN amount_usd ELSE 0 END), 0)
                                               AS total_granted_usd,
                -- total spent = abs(sum of COMMIT entries only)
                COALESCE(ABS(SUM(CASE WHEN entry_type = 'COMMIT' THEN amount_usd ELSE 0 END)), 0)
                                               AS total_spent_usd,
                NOW()                          AS created_at,
                NOW()                          AS last_updated_at
            FROM budget_ledger
            GROUP BY user_id
            ON CONFLICT (user_id) DO NOTHING;
            """
        )
    )

    # ------------------------------------------------------------------ #
    # 4. Backfill session_reservations for ACTIVE/in-flight sessions      #
    #    These are sessions with a RESERVE ledger entry but no RELEASE.   #
    # ------------------------------------------------------------------ #
    op.execute(
        sa.text(
            """
            INSERT INTO session_reservations (
                user_id,
                blog_session_id,
                reserved_usd,
                reserved_tokens,
                actual_usd,
                actual_tokens,
                status,
                created_at,
                updated_at
            )
            SELECT
                r.user_id,
                r.blog_session_id,
                ABS(r.reserved_usd)            AS reserved_usd,
                ABS(r.reserved_tokens)         AS reserved_tokens,
                COALESCE(ABS(c.committed_usd), 0)  AS actual_usd,
                COALESCE(ABS(c.committed_tokens), 0) AS actual_tokens,
                CASE
                    WHEN bs.status IN ('COMPLETED') THEN 'COMMITTED'
                    WHEN bs.status IN ('FAILED', 'CANCELLED') THEN 'RELEASED'
                    ELSE 'ACTIVE'
                END                            AS status,
                NOW()                          AS created_at,
                NOW()                          AS updated_at
            FROM (
                SELECT user_id, blog_session_id,
                       SUM(amount_usd) AS reserved_usd,
                       SUM(tokens) AS reserved_tokens
                FROM budget_ledger
                WHERE entry_type = 'RESERVE' AND blog_session_id IS NOT NULL
                GROUP BY user_id, blog_session_id
            ) r
            LEFT JOIN (
                SELECT blog_session_id,
                       SUM(amount_usd) AS committed_usd,
                       SUM(tokens) AS committed_tokens
                FROM budget_ledger
                WHERE entry_type = 'COMMIT' AND blog_session_id IS NOT NULL
                GROUP BY blog_session_id
            ) c ON c.blog_session_id = r.blog_session_id
            LEFT JOIN blog_sessions bs ON bs.id = r.blog_session_id
            ON CONFLICT (blog_session_id) DO NOTHING;
            """
        )
    )


def downgrade() -> None:
    op.drop_table("session_reservations")
    op.drop_table("budget_accounts")
