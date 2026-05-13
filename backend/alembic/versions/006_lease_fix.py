"""Harden budget ledger queries and reaper accounting."""

from __future__ import annotations

from alembic import op

revision = "006_lease_fix"
down_revision = "005_lease_based_ownership"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_budget_ledger_end_user_resource_day",
        "budget_ledger",
        ["end_user_id", "resource_type", "created_at"],
    )
    op.create_index(
        "ix_budget_ledger_session_resource_entry",
        "budget_ledger",
        ["blog_session_id", "resource_type", "entry_type"],
    )
    op.create_index(
        "ix_budget_ledger_tenant_resource_day",
        "budget_ledger",
        ["tenant_id", "resource_type", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_budget_ledger_tenant_resource_day", table_name="budget_ledger")
    op.drop_index("ix_budget_ledger_session_resource_entry", table_name="budget_ledger")
    op.drop_index("ix_budget_ledger_end_user_resource_day", table_name="budget_ledger")
