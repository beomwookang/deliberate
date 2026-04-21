"""Add approval_group_id to approvals for multi-approver flows.

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "approvals",
        sa.Column("approval_group_id", UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "approvals",
        sa.Column("approval_mode", sa.Text(), nullable=True),
    )
    op.create_index(
        "idx_approvals_group",
        "approvals",
        ["approval_group_id"],
        postgresql_where=sa.text("approval_group_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_approvals_group", table_name="approvals")
    op.drop_column("approvals", "approval_mode")
    op.drop_column("approvals", "approval_group_id")
