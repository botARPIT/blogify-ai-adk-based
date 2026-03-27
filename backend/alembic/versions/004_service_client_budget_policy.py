"""Add service-client daily budget policies.

This stores explicit per-service-client daily USD caps used to derive
temporary generation lockout until the next UTC day boundary.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "004_service_client_budget_policy"
down_revision = "003_local_auth_notifications"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "service_client_budget_policies",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "service_client_id",
            sa.BigInteger(),
            sa.ForeignKey("service_clients.id"),
            nullable=False,
        ),
        sa.Column("daily_budget_limit_usd", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("currency_code", sa.String(length=8), nullable=False, server_default="USD"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("service_client_id", name="uq_service_client_budget_policy"),
    )
    op.create_index(
        "ix_service_client_budget_policies_service_client_id",
        "service_client_budget_policies",
        ["service_client_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_service_client_budget_policies_service_client_id",
        table_name="service_client_budget_policies",
    )
    op.drop_table("service_client_budget_policies")
