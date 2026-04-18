"""Initial schema per PRD §6.3.

Revision ID: 0001
Revises: None
Create Date: 2026-04-19
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # applications — reserved for multi-tenancy (PRD §6.5)
    op.create_table(
        "applications",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("api_key_hash", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )

    # interrupts
    op.create_table(
        "interrupts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "application_id",
            sa.Text(),
            sa.ForeignKey("applications.id"),
            nullable=False,
            server_default=sa.text("'default'"),
        ),
        sa.Column("thread_id", sa.Text(), nullable=False),
        sa.Column("trace_id", sa.Text(), nullable=True),
        sa.Column("layout", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("policy_name", sa.Text(), nullable=True),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index(
        "idx_interrupts_thread", "interrupts", ["application_id", "thread_id"]
    )

    # approvals
    op.create_table(
        "approvals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "interrupt_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("interrupts.id"),
            nullable=False,
        ),
        sa.Column("approver_id", sa.Text(), nullable=True),
        sa.Column("acting_for", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("timeout_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "escalated_to",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("approvals.id"),
            nullable=True,
        ),
        sa.Column("delegation_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index(
        "idx_approvals_pending",
        "approvals",
        ["status", "timeout_at"],
        postgresql_where=sa.text("status = 'pending'"),
    )

    # decisions
    op.create_table(
        "decisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "approval_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("approvals.id"),
            nullable=False,
        ),
        sa.Column("approver_email", sa.Text(), nullable=False),
        sa.Column("decision_type", sa.Text(), nullable=False),
        sa.Column("decision_payload", postgresql.JSONB(), nullable=True),
        sa.Column("rationale_category", sa.Text(), nullable=True),
        sa.Column("rationale_notes", sa.Text(), nullable=True),
        sa.Column("decided_via", sa.Text(), nullable=False),
        sa.Column("review_duration_ms", sa.Integer(), nullable=True),
        sa.Column("signature", sa.Text(), nullable=False),
        sa.Column(
            "decided_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )

    # ledger_entries — canonical business record (PRD §5.3, §6.5)
    op.create_table(
        "ledger_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "application_id",
            sa.Text(),
            sa.ForeignKey("applications.id"),
            nullable=False,
            server_default=sa.text("'default'"),
        ),
        sa.Column(
            "interrupt_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("interrupts.id"),
            nullable=False,
        ),
        sa.Column(
            "decision_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("decisions.id"),
            nullable=True,
        ),
        sa.Column("resume_status", sa.Text(), nullable=False),
        sa.Column("resume_latency_ms", sa.Integer(), nullable=True),
        sa.Column("content", postgresql.JSONB(), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index(
        "idx_ledger_thread",
        "ledger_entries",
        ["application_id", sa.text("(content->>'thread_id')")],
    )
    op.create_index(
        "idx_ledger_created",
        "ledger_entries",
        ["application_id", sa.column("created_at").desc()],
    )

    # approvers — directory with reserved OOO fields (PRD §6.3)
    op.create_table(
        "approvers",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=True),
        sa.Column("ooo_active", sa.Boolean(), server_default=sa.text("FALSE")),
        sa.Column("ooo_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ooo_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "ooo_delegate_to", sa.Text(), sa.ForeignKey("approvers.id"), nullable=True
        ),
    )

    # Seed default application row (PRD §6.5)
    op.execute(
        "INSERT INTO applications (id, display_name, api_key_hash) "
        "VALUES ('default', 'Default Application', 'placeholder-replace-on-first-use')"
    )


def downgrade() -> None:
    op.drop_table("approvers")
    op.drop_table("ledger_entries")
    op.drop_table("decisions")
    op.drop_table("approvals")
    op.drop_table("interrupts")
    op.drop_table("applications")
