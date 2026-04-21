"""Add notification_attempts table for ops visibility (PRD §6.3 v4).

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-22
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers
revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "notification_attempts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "application_id",
            sa.Text(),
            sa.ForeignKey("applications.id"),
            nullable=False,
            server_default=sa.text("'default'"),
        ),
        sa.Column(
            "approval_id",
            UUID(as_uuid=True),
            sa.ForeignKey("approvals.id"),
            nullable=False,
        ),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("approver_email", sa.Text(), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("message_id", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column(
            "attempted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index(
        "idx_notifications_approval",
        "notification_attempts",
        ["application_id", "approval_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_notifications_approval", table_name="notification_attempts")
    op.drop_table("notification_attempts")
