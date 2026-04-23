"""Pydantic models matching PRD §5.1 (InterruptPayload), §5.3 (LedgerEntry), and supporting types.

These schemas are the API boundaries Deliberate commits to for v1.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class DeliberateError(Exception):
    """Base exception for Deliberate SDK errors."""


class DeliberateTimeoutError(DeliberateError):
    """Raised when client-side polling exceeds the configured timeout.

    This means the SDK gave up waiting — the approval may still be pending
    on the server. Check the Deliberate UI or server logs for status.
    """

    def __init__(self, approval_id: str, timeout_seconds: int) -> None:
        self.approval_id = approval_id
        self.timeout_seconds = timeout_seconds
        super().__init__(
            f"Timed out after {timeout_seconds}s waiting for approval {approval_id}. "
            "The approval may still be pending on the server."
        )


class DeliberateServerError(DeliberateError):
    """Raised when the Deliberate server returns an error."""

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"Server error {status_code}: {detail}")


class MoneyAmount(BaseModel):
    """Monetary amount with currency code (PRD §5.1)."""

    value: float
    currency: str = "USD"


class Evidence(BaseModel):
    """A piece of evidence supporting the agent's recommendation (PRD §5.1)."""

    type: str
    id: str | None = None
    summary: str
    url: str | None = None


class DecisionOption(BaseModel):
    """An available decision action presented to the approver (PRD §5.1).

    Decision types: approve, modify, escalate, reject.
    """

    type: str
    label: str
    fields: list[str] | None = None


class AgentReasoningStructured(BaseModel):
    """Structured form of agent reasoning (PRD §5.1 v3).

    Use when reasoning is complex enough to benefit from bullet points.
    The UI renders summary prominently, points[] as a list, and uses
    confidence to visually flag low-evidence decisions.
    """

    summary: str
    points: list[str] | None = None
    confidence: str | None = None  # "high" | "medium" | "low"


class InterruptPayload(BaseModel):
    """What the SDK captures when a LangGraph node calls interrupt() inside an @approval_gate.

    See PRD §5.1 for the full specification. The payload is everything an approver needs
    to decide, plus everything a future auditor needs to understand the context.
    """

    layout: str = Field(..., description="Layout identifier (e.g. 'financial_decision')")
    subject: str = Field(..., description="One-line header for the approval request")

    # Layout-specific fields — passed through to the layout component
    amount: MoneyAmount | None = None
    customer: dict[str, Any] | None = None
    agent_reasoning: str | AgentReasoningStructured | None = None
    evidence: list[Evidence] | None = None

    # Decision mechanics
    decision_options: list[DecisionOption] | None = None
    rationale_categories: list[str] | None = None

    # Pass-through metadata for the ledger
    metadata: dict[str, Any] | None = None


class PolicyEvaluation(BaseModel):
    """Result of policy evaluation recorded in the ledger (PRD §5.3)."""

    matched_rule: str
    policy_name: str
    policy_version_hash: str


class ApprovalRecord(BaseModel):
    """The approval section of a ledger entry (PRD §5.3)."""

    approver_id: str
    approver_email: str
    acting_for: str | None = None  # Reserved for v1.1+: populated for delegated decisions
    decided_at: datetime
    decision_type: str  # approve, modify, escalate, reject
    decision_payload: dict[str, Any] | None = None
    rationale_category: str | None = None
    rationale_notes: str | None = None
    channel: str  # slack, email, webhook
    decided_via: str  # web_ui, api, slack_inline, email
    review_duration_ms: int | None = None


class EscalationRecord(BaseModel):
    """An escalation event recorded in the ledger (PRD §5.3)."""

    from_approver: str
    to_approver: str
    reason: str
    escalated_at: datetime


class ResumeRecord(BaseModel):
    """Resume outcome recorded in the ledger (PRD §5.3)."""

    resumed_at: datetime
    resume_latency_ms: int
    resume_status: str  # success, error


class ApprovalGroupRecord(BaseModel):
    """Group metadata for multi-approver flows."""

    group_id: str | None = None
    role: str | None = None  # "one_of_many" | "sole_decider" | "contributor_to_all_of"


class LedgerEntry(BaseModel):
    """The structured record written when an approval decision completes.

    The ledger entry is the canonical business record (PRD §5.3, §6.5).
    All other tables in Deliberate's database are operational projections.
    Entries are append-only and immutable once written.
    """

    id: str = Field(..., description="Ledger entry ID (e.g. 'ledger_01HGQ3...')")
    created_at: datetime
    thread_id: str
    trace_id: str | None = None
    application_id: str = "default"  # Reserved: see PRD §6.5 on tenant model

    interrupt: InterruptPayload
    policy_evaluation: PolicyEvaluation

    approval: ApprovalRecord | None = None  # NULL if timed_out with no decision
    approval_group: ApprovalGroupRecord | None = None
    escalations: list[EscalationRecord] = Field(default_factory=list)
    prev_hash: str | None = Field(None, description="Content hash of previous ledger entry")
    resume: ResumeRecord | None = None

    content_hash: str = Field(..., description="SHA-256 of all preceding fields")
    signature: str = Field(..., description="Server signature over content_hash")


class Decision(BaseModel):
    """The decision submitted by an approver, used by the SDK to resume the graph."""

    id: UUID
    decision_type: str  # approve, modify, escalate, reject
    decision_payload: dict[str, Any] | None = None
    rationale_category: str | None = None
    rationale_notes: str | None = None


# ---------------------------------------------------------------------------
# Approver directory types (PRD §5.2) — shared between SDK and server
# ---------------------------------------------------------------------------


class OutOfOffice(BaseModel):
    """Out-of-office configuration for an approver. Schema-reserved, inert until v1.1."""

    active: bool = False
    from_date: datetime | None = Field(None, alias="from")
    until: datetime | None = None
    delegate_to: str | None = None


class ApproverEntry(BaseModel):
    """An individual approver in the directory (PRD §5.2)."""

    id: str
    email: str
    display_name: str | None = None
    out_of_office: OutOfOffice = Field(default_factory=OutOfOffice)


class ApproverGroup(BaseModel):
    """A named group of approvers (PRD §5.2)."""

    id: str
    members: list[str]


class ApproverDirectoryConfig(BaseModel):
    """Top-level structure of approvers.yaml (PRD §5.2)."""

    approvers: list[ApproverEntry] = Field(default_factory=list)
    groups: list[ApproverGroup] = Field(default_factory=list)


class ResolvedApprover(BaseModel):
    """An approver resolved to concrete email + display name."""

    id: str
    email: str
    display_name: str | None = None
