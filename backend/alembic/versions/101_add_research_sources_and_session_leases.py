"""Add research_sources and session_leases tables, user_id to agent_runs.

Revision ID: 101
Revises: 015_session_leases
Create Date: 2026-05-08

1. Add user_id column to agent_runs
2. Create research_sources table for storing Tavily research data
3. Create session_leases table for append-only lease audit trail
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '101'
down_revision: Union[str, Sequence[str], None] = '015_session_leases'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add user_id to agent_runs - first make existing rows have a user
    # Get user_id from blog_session for existing rows
    op.execute("""
        UPDATE agent_runs 
        SET user_id = bs.user_id 
        FROM blog_sessions bs 
        WHERE agent_runs.blog_session_id = bs.id
        AND agent_runs.user_id IS NULL
    """)
    
    op.add_column('agent_runs', sa.Column('user_id', sa.Integer(), nullable=False, server_default='1'))
    op.alter_column('agent_runs', 'user_id', server_default=None)
    op.create_index('ix_agent_runs_user_id', 'agent_runs', ['user_id'])
    op.create_foreign_key(
        'fk_agent_runs_user_id', 
        'agent_runs', 'auth_users', 
        ['user_id'], ['id'], 
        ondelete='CASCADE'
    )

    # 2. Create research_sources table
    op.create_table(
        'research_sources',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('blog_session_id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=500), nullable=False),
        sa.Column('url', sa.String(length=2048), nullable=False),
        sa.Column('content', sa.Text(), nullable=True),
        sa.Column('score', sa.Numeric(precision=5, scale=4), nullable=False, server_default='0'),
        sa.Column('topic', sa.String(length=500), nullable=True),
        sa.Column('collected_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_research_sources_session', 'research_sources', ['blog_session_id'])
    op.create_index('ix_research_sources_user', 'research_sources', ['user_id'])
    op.create_foreign_key(
        'fk_research_sources_user',
        'research_sources', 'auth_users',
        ['user_id'], ['id'],
        ondelete='CASCADE'
    )
    op.create_foreign_key(
        'fk_research_sources_session',
        'research_sources', 'blog_sessions',
        ['blog_session_id'], ['id'],
        ondelete='CASCADE'
    )

    # 3. Create session_leases table for append-only lease audit
    op.create_table(
        'session_leases',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('blog_session_id', sa.Integer(), nullable=False),
        sa.Column('lease_owner', sa.String(length=255), nullable=False),
        sa.Column('lease_expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('lease_version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('last_heartbeat_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('release_reason', sa.String(length=50), nullable=True),
    )
    op.create_index('ix_session_leases_session', 'session_leases', ['blog_session_id'])
    op.create_index('ix_session_leases_owner', 'session_leases', ['lease_owner'])
    op.create_index('ix_session_leases_started', 'session_leases', ['started_at'])
    op.create_index('ix_session_leases_ended', 'session_leases', ['ended_at'])
    op.create_foreign_key(
        'fk_session_leases_session',
        'session_leases', 'blog_sessions',
        ['blog_session_id'], ['id'],
        ondelete='CASCADE'
    )


def downgrade() -> None:
    op.drop_table('session_leases')
    op.drop_table('research_sources')
    op.drop_column('agent_runs', 'user_id')