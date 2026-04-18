"""SQLAlchemy models matching PRD §6.3.

Every table that carries business data includes application_id, indexed leading with it,
as specified in §6.5 (tenant model). Reserved fields for v1.1+ delegation are present
but inert.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Application(Base):
    """Reserved for multi-tenancy (PRD §6.5). Single default row in v1.0."""

    __tablename__ = "applications"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    api_key_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )


class Interrupt(Base):
    """An interrupt captured by the SDK and submitted to the server (PRD §6.3)."""

    __tablename__ = "interrupts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    application_id: Mapped[str] = mapped_column(
        Text, ForeignKey("applications.id"), nullable=False, server_default=text("'default'")
    )
    thread_id: Mapped[str] = mapped_column(Text, nullable=False)
    trace_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    layout: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)  # type: ignore[type-arg]
    policy_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )

    __table_args__ = (Index("idx_interrupts_thread", "application_id", "thread_id"),)


class Approval(Base):
    """Operational state for a pending or completed approval (PRD §6.3)."""

    __tablename__ = "approvals"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    interrupt_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("interrupts.id"), nullable=False
    )
    approver_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    acting_for: Mapped[str | None] = mapped_column(Text, nullable=True)  # Reserved for v1.1+
    # pending, decided, timed_out, escalated
    status: Mapped[str] = mapped_column(Text, nullable=False)
    timeout_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    escalated_to: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("approvals.id"), nullable=True
    )
    delegation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)  # Reserved for v1.1+
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )

    __table_args__ = (
        Index(
            "idx_approvals_pending",
            "status",
            "timeout_at",
            postgresql_where=text("status = 'pending'"),
        ),
    )


class Decision(Base):
    """The structured record of an approver's response (PRD §6.3)."""

    __tablename__ = "decisions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    approval_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("approvals.id"), nullable=False
    )
    approver_email: Mapped[str] = mapped_column(Text, nullable=False)
    # approve, modify, escalate, reject
    decision_type: Mapped[str] = mapped_column(Text, nullable=False)
    decision_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # type: ignore[type-arg]
    rationale_category: Mapped[str | None] = mapped_column(Text, nullable=True)
    rationale_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # web_ui, api, slack_inline, email
    decided_via: Mapped[str] = mapped_column(Text, nullable=False)
    review_duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    signature: Mapped[str] = mapped_column(Text, nullable=False)
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )


class LedgerEntry(Base):
    """Append-only canonical business record (PRD §5.3, §6.3, §6.5).

    The content column holds the full JSON per §5.3 — this is the source of truth.
    """

    __tablename__ = "ledger_entries"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    application_id: Mapped[str] = mapped_column(
        Text, ForeignKey("applications.id"), nullable=False, server_default=text("'default'")
    )
    interrupt_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("interrupts.id"), nullable=False
    )
    decision_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("decisions.id"), nullable=True
    )
    resume_status: Mapped[str] = mapped_column(Text, nullable=False)
    resume_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content: Mapped[dict] = mapped_column(JSONB, nullable=False)  # type: ignore[type-arg]
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )

    __table_args__ = (
        Index("idx_ledger_thread", "application_id", text("(content->>'thread_id')")),
        Index("idx_ledger_created", "application_id", "created_at"),
    )


class Approver(Base):
    """Approver directory with reserved OOO fields for v1.1+ (PRD §6.3)."""

    __tablename__ = "approvers"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    ooo_active: Mapped[bool] = mapped_column(Boolean, default=False)  # Reserved for v1.1+
    ooo_from: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )  # Reserved
    ooo_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )  # Reserved
    ooo_delegate_to: Mapped[str | None] = mapped_column(
        Text, ForeignKey("approvers.id"), nullable=True
    )  # Reserved for v1.1+
