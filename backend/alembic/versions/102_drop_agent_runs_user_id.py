"""Drop user_id column from agent_runs table.

Revision ID: 102
Revises: 101
Create Date: 2026-05-08

Removes user_id column from agent_runs table as it was incorrectly added.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '102'
down_revision: Union[str, Sequence[str], None] = '101'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index('ix_agent_runs_user_id', table_name='agent_runs')
    op.drop_constraint('fk_agent_runs_user_id', table_name='agent_runs', type_='foreignkey')
    op.drop_column('agent_runs', 'user_id')


def downgrade() -> None:
    op.add_column('agent_runs', sa.Column('user_id', sa.Integer(), nullable=False, server_default='1'))
    op.alter_column('agent_runs', 'user_id', server_default=None)
    op.create_index('ix_agent_runs_user_id', 'agent_runs', ['user_id'])
    op.create_foreign_key(
        'fk_agent_runs_user_id',
        'agent_runs', 'auth_users',
        ['user_id'], ['id'],
        ondelete='CASCADE'
    )