"""Add resume_events table and prev_hash to ledger_entries (M3b).

Revision ID: 0005
Revises: 0004
Create Date: 2026-04-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Create resume_events table
    op.create_table(
        "resume_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "ledger_entry_id",
            UUID(as_uuid=True),
            sa.ForeignKey("ledger_entries.id"),
            nullable=False,
        ),
        sa.Column("resume_status", sa.Text(), nullable=False),
        sa.Column("resume_latency_ms", sa.Integer(), nullable=True),
        sa.Column(
            "resumed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index(
        "idx_resume_events_ledger",
        "resume_events",
        ["ledger_entry_id"],
    )

    # Add prev_hash column to ledger_entries
    op.add_column(
        "ledger_entries",
        sa.Column("prev_hash", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ledger_entries", "prev_hash")
    op.drop_index("idx_resume_events_ledger", table_name="resume_events")
    op.drop_table("resume_events")
