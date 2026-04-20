"""Approval endpoints: status polling, payload fetch, decision, resume ACK (PRD §6.2, §6.4)."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from deliberate_server.auth import compute_content_hash, sign_content_hash, sign_decision
from deliberate_server.db.models import Approval, Decision, Interrupt
from deliberate_server.db.models import LedgerEntry as LedgerEntryModel
from deliberate_server.db.session import async_session

logger = logging.getLogger("deliberate_server.api.approvals")

router = APIRouter(prefix="/approvals", tags=["approvals"])


# --- Response models ---


class StatusResponse(BaseModel):
    status: str
    approval_id: str
    decision_type: str | None = None
    decision_payload: dict[str, Any] | None = None
    rationale_category: str | None = None
    rationale_notes: str | None = None


class PayloadResponse(BaseModel):
    approval_id: str
    status: str
    layout: str
    payload: dict[str, Any]


DecisionType = Literal["approve", "modify", "escalate", "reject"]


class DecideRequest(BaseModel):
    decision_type: DecisionType
    decision_payload: dict[str, Any] | None = None
    rationale_category: str | None = None
    rationale_notes: str | None = None
    approver_email: str
    review_duration_ms: int | None = None
    decided_via: str = "web_ui"


class DecideResponse(BaseModel):
    status: str


class ResumeAckRequest(BaseModel):
    resume_status: str
    resume_latency_ms: int


class ResumeAckResponse(BaseModel):
    ok: bool


# --- Endpoints ---


@router.get("/{approval_id}/status", response_model=StatusResponse)
async def get_approval_status(approval_id: uuid.UUID) -> StatusResponse:
    """Poll for approval status. No auth for M1 — approval_id is the secret."""
    async with async_session() as session:
        approval = await session.get(Approval, approval_id)
        if approval is None:
            raise HTTPException(status_code=404, detail="Approval not found")

        if approval.status != "decided":
            return StatusResponse(
                status=approval.status,
                approval_id=str(approval_id),
            )

        # Fetch the decision
        result = await session.execute(select(Decision).where(Decision.approval_id == approval_id))
        decision = result.scalar_one_or_none()
        if decision is None:
            return StatusResponse(status=approval.status, approval_id=str(approval_id))

        return StatusResponse(
            status="decided",
            approval_id=str(approval_id),
            decision_type=decision.decision_type,
            decision_payload=decision.decision_payload,
            rationale_category=decision.rationale_category,
            rationale_notes=decision.rationale_notes,
        )


# TODO(M2): Replace with signed token per PRD §6.6
@router.get("/{approval_id}/payload", response_model=PayloadResponse)
async def get_approval_payload(approval_id: uuid.UUID) -> PayloadResponse:
    """Fetch the interrupt payload for rendering the approval UI."""
    async with async_session() as session:
        approval = await session.get(Approval, approval_id)
        if approval is None:
            raise HTTPException(status_code=404, detail="Approval not found")

        interrupt = await session.get(Interrupt, approval.interrupt_id)
        if interrupt is None:
            raise HTTPException(status_code=404, detail="Interrupt not found")

        return PayloadResponse(
            approval_id=str(approval_id),
            status=approval.status,
            layout=interrupt.layout,
            payload=interrupt.payload,
        )


@router.post("/{approval_id}/decide", response_model=DecideResponse)
async def submit_decision(approval_id: uuid.UUID, body: DecideRequest) -> DecideResponse:
    """Submit a decision for an approval."""
    now = datetime.now(UTC)

    async with async_session() as session, session.begin():
        approval = await session.get(Approval, approval_id)
        if approval is None:
            raise HTTPException(status_code=404, detail="Approval not found")

        if approval.status != "pending":
            raise HTTPException(
                status_code=409,
                detail=f"Approval is already {approval.status}, cannot decide",
            )

        # Fetch the interrupt for ledger construction
        interrupt = await session.get(Interrupt, approval.interrupt_id)
        if interrupt is None:
            raise HTTPException(status_code=404, detail="Interrupt not found")

        # Sign the decision
        decision_fields = {
            "approval_id": str(approval_id),
            "decision_type": body.decision_type,
            "decision_payload": body.decision_payload,
            "approver_email": body.approver_email,
            "decided_at": now.isoformat(),
        }
        signature = sign_decision(decision_fields)

        # Create decision row
        decision_id = uuid.uuid4()
        decision_row = Decision(
            id=decision_id,
            approval_id=approval_id,
            approver_email=body.approver_email,
            decision_type=body.decision_type,
            decision_payload=body.decision_payload,
            rationale_category=body.rationale_category,
            rationale_notes=body.rationale_notes,
            decided_via=body.decided_via,
            review_duration_ms=body.review_duration_ms,
            signature=signature,
            decided_at=now,
        )
        session.add(decision_row)

        # Update approval status
        approval.status = "decided"

        # Build ledger content per PRD §5.3
        ledger_content: dict[str, Any] = {
            "id": str(uuid.uuid4()),
            "created_at": now.isoformat(),
            "thread_id": interrupt.thread_id,
            "trace_id": interrupt.trace_id,
            "application_id": interrupt.application_id,
            "interrupt": interrupt.payload,
            "policy_evaluation": {
                "matched_rule": "m1_default",
                "policy_name": "m1_env_approver",
                "policy_version_hash": "sha256:m1-no-policy",
            },
            "approval": {
                "approver_id": approval.approver_id,
                "approver_email": body.approver_email,
                "acting_for": None,
                "decided_at": now.isoformat(),
                "decision_type": body.decision_type,
                "decision_payload": body.decision_payload,
                "rationale_category": body.rationale_category,
                "rationale_notes": body.rationale_notes,
                "channel": "none",
                "decided_via": body.decided_via,
                "review_duration_ms": body.review_duration_ms,
            },
            "escalations": [],
            "resume": None,
        }

        # Compute content hash (excluding signature)
        content_hash = compute_content_hash(ledger_content)
        content_signature = sign_content_hash(content_hash)

        # Add hash + signature to the content
        ledger_content["content_hash"] = content_hash
        ledger_content["signature"] = content_signature

        # Validate content against SDK's LedgerEntry schema (D-1 fix)
        from deliberate.types import LedgerEntry as LedgerEntrySchema

        try:
            LedgerEntrySchema.model_validate(ledger_content)
        except Exception as e:
            logger.error(
                "CRITICAL: Ledger content failed schema validation for approval %s: %s",
                approval_id,
                e,
            )
            raise HTTPException(
                status_code=500,
                detail="Internal error: ledger content schema validation failed",
            ) from e

        # Create ledger entry
        ledger_entry = LedgerEntryModel(
            id=uuid.UUID(ledger_content["id"]),
            application_id=interrupt.application_id,
            interrupt_id=interrupt.id,
            decision_id=decision_id,
            resume_status="pending",
            resume_latency_ms=None,
            content=ledger_content,
            content_hash=content_hash,
        )
        session.add(ledger_entry)

    logger.info("Decision recorded for approval %s: %s", approval_id, body.decision_type)
    return DecideResponse(status="decided")


@router.post("/{approval_id}/resume-ack", response_model=ResumeAckResponse)
async def resume_ack(approval_id: uuid.UUID, body: ResumeAckRequest) -> ResumeAckResponse:
    """Acknowledge graph resume. Updates ledger entry with final resume status."""
    async with async_session() as session, session.begin():
        # Find the ledger entry for this approval
        result = await session.execute(
            select(LedgerEntryModel)
            .join(
                Decision,
                LedgerEntryModel.decision_id == Decision.id,
            )
            .where(Decision.approval_id == approval_id)
        )
        ledger_entry = result.scalar_one_or_none()

        if ledger_entry is None:
            raise HTTPException(status_code=404, detail="Ledger entry not found for approval")

        # Update resume fields
        ledger_entry.resume_status = body.resume_status
        ledger_entry.resume_latency_ms = body.resume_latency_ms

        # Update the content JSON as well
        content = dict(ledger_entry.content)
        content["resume"] = {
            "resumed_at": datetime.now(UTC).isoformat(),
            "resume_latency_ms": body.resume_latency_ms,
            "resume_status": body.resume_status,
        }
        # Recompute hash after resume update
        excluded = ("content_hash", "signature")
        content_without_sig = {k: v for k, v in content.items() if k not in excluded}
        new_hash = compute_content_hash(content_without_sig)
        new_sig = sign_content_hash(new_hash)
        content["content_hash"] = new_hash
        content["signature"] = new_sig
        ledger_entry.content = content
        ledger_entry.content_hash = new_hash

    return ResumeAckResponse(ok=True)
