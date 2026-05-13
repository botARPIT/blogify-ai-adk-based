"""Migration 107 — replace multi-tenant blog_sessions schema with simple user_id schema.

Revision ID: 107
Revises: 106
Create Date: 2026-05-14

Replace the multi-tenant blog_sessions schema with a simple user_id schema
matching the dev ORM. Drops all dependent tables first, recreates blog_sessions,
agent_runs, research_sources, session_leases, session_reservations with
the simple schema. Downgrade not supported — restore from snapshot to roll back.
"""

from __future__ import annotations

from alembic import op

revision = "107"
down_revision = "106"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS user_notifications CASCADE")
    op.execute("DROP TABLE IF EXISTS human_review_events CASCADE")
    op.execute("DROP TABLE IF EXISTS session_reservations CASCADE")
    op.execute("DROP TABLE IF EXISTS session_leases CASCADE")
    op.execute("DROP TABLE IF EXISTS budget_reservations CASCADE")
    op.execute("DROP TABLE IF EXISTS research_sources CASCADE")
    op.execute("DROP TABLE IF EXISTS agent_runs CASCADE")
    op.execute("DROP TABLE IF EXISTS blog_versions CASCADE")
    op.execute("DROP TABLE IF EXISTS export_jobs CASCADE")

    op.execute("DROP TABLE IF EXISTS tenants CASCADE")
    op.execute("DROP TABLE IF EXISTS end_users CASCADE")
    op.execute("DROP TABLE IF EXISTS service_clients CASCADE")
    op.execute("DROP TABLE IF EXISTS service_client_budget_policies CASCADE")
    op.execute("DROP TABLE IF EXISTS budget_policies CASCADE")

    op.execute("DROP TABLE IF EXISTS blog_sessions CASCADE")
    op.execute("DROP TYPE IF EXISTS blog_session_status_enum CASCADE")

    op.execute("""
        CREATE TABLE blog_sessions (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES auth_users(id) ON DELETE CASCADE,
            topic VARCHAR(500) NOT NULL,
            audience VARCHAR(255) NOT NULL DEFAULT 'general readers',
            tone VARCHAR(100) NOT NULL DEFAULT 'professional',
            status VARCHAR(50) NOT NULL DEFAULT 'QUEUED',
            current_stage VARCHAR(50),
            adk_session_id VARCHAR(255),
            invocation_id VARCHAR(255),
            confirmation_request_id VARCHAR(255),
            outline_data JSONB,
            final_content TEXT,
            budget_reserved_tokens INTEGER NOT NULL DEFAULT 0,
            budget_spent_tokens INTEGER NOT NULL DEFAULT 0,
            budget_reserved_usd NUMERIC(12,8) NOT NULL DEFAULT 0,
            budget_spent_usd NUMERIC(12,8) NOT NULL DEFAULT 0,
            reap_count INTEGER NOT NULL DEFAULT 0,
            idempotency_key VARCHAR(255),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            completed_at TIMESTAMPTZ,
            failed_at TIMESTAMPTZ,
            failure_reason TEXT
        )
    """)
    op.execute("CREATE INDEX ix_blog_sessions_status ON blog_sessions (status)")
    op.execute("CREATE INDEX ix_blog_sessions_user_id ON blog_sessions (user_id)")
    op.execute("""
        ALTER TABLE blog_sessions
        ADD CONSTRAINT uq_blog_sessions_idempotency
        UNIQUE (user_id, idempotency_key)
    """)

    op.execute("""
        CREATE TABLE agent_runs (
            id SERIAL PRIMARY KEY,
            blog_session_id INTEGER REFERENCES blog_sessions(id) ON DELETE CASCADE,
            stage VARCHAR(80),
            status VARCHAR(50),
            started_at TIMESTAMPTZ DEFAULT now(),
            completed_at TIMESTAMPTZ,
            output_snapshot JSONB,
            token_count INTEGER DEFAULT 0,
            cost_usd NUMERIC(12,8) DEFAULT 0,
            latency_ms INTEGER,
            error_message TEXT
        )
    """)

    op.execute("""
        CREATE TABLE research_sources (
            id SERIAL PRIMARY KEY,
            blog_session_id INTEGER NOT NULL REFERENCES blog_sessions(id) ON DELETE CASCADE,
            url TEXT,
            title TEXT,
            snippet TEXT,
            created_at TIMESTAMPTZ DEFAULT now()
        )
    """)
    op.execute("""
        CREATE INDEX fk_research_sources_session
        ON research_sources (blog_session_id)
    """)

    op.execute("""
        CREATE TABLE session_leases (
            id SERIAL PRIMARY KEY,
            blog_session_id INTEGER NOT NULL REFERENCES blog_sessions(id) ON DELETE CASCADE,
            worker_id VARCHAR(255),
            acquired_at TIMESTAMPTZ DEFAULT now(),
            expires_at TIMESTAMPTZ,
            released_at TIMESTAMPTZ
        )
    """)
    op.execute("""
        CREATE INDEX fk_session_leases_session
        ON session_leases (blog_session_id)
    """)

    op.execute("""
        CREATE TABLE session_reservations (
            id SERIAL PRIMARY KEY,
            blog_session_id INTEGER NOT NULL REFERENCES blog_sessions(id) ON DELETE CASCADE,
            reserved_tokens INTEGER NOT NULL DEFAULT 0,
            reserved_usd NUMERIC(12,8) NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ DEFAULT now(),
            released_at TIMESTAMPTZ
        )
    """)

    op.execute("""
        ALTER TABLE budget_ledger
        DROP CONSTRAINT IF EXISTS budget_ledger_blog_session_id_fkey
    """)
    op.execute("""
        UPDATE budget_ledger
        SET blog_session_id = NULL
        WHERE blog_session_id IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM blog_sessions WHERE id = budget_ledger.blog_session_id)
    """)
    op.execute("""
        ALTER TABLE budget_ledger
        ADD CONSTRAINT budget_ledger_blog_session_id_fkey
        FOREIGN KEY (blog_session_id) REFERENCES blog_sessions(id) ON DELETE SET NULL
    """)

    op.execute("""
        ALTER TABLE budget_accounts
        DROP CONSTRAINT IF EXISTS budget_accounts_user_id_fkey
    """)
    op.execute("""
        ALTER TABLE budget_accounts
        ADD CONSTRAINT budget_accounts_user_id_fkey
        FOREIGN KEY (user_id) REFERENCES auth_users(id) ON DELETE CASCADE
    """)


def downgrade() -> None:
    raise NotImplementedError(
        "Downgrade not supported for migration 107 — restore from a database snapshot to roll back"
    )
