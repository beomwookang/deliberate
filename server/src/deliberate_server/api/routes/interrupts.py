"""Interrupt submission endpoint (PRD §6.2, §6.4 step 2).

Uses policy engine to evaluate interrupts and resolve approvers.
Falls back to DEFAULT_APPROVER_EMAIL if no policy matches (deprecated).
"""

from __future__ import annotations

import json as _json
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from deliberate.types import InterruptPayload, ResolvedApprover
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from deliberate_server.auth import (
    compute_content_hash,
    sign_content_hash,
    verify_api_key,
)
from deliberate_server.config import settings
from deliberate_server.db.models import Application, Approval, Interrupt
from deliberate_server.db.models import LedgerEntry as LedgerEntryModel
from deliberate_server.db.session import async_session
from deliberate_server.metrics import INTERRUPTS_TOTAL
from deliberate_server.notify import notification_dispatcher
from deliberate_server.policy import NoMatchingPolicyError, policy_engine
from deliberate_server.policy.types import ResolvedPlan
from deliberate_server.telemetry import emit_ledger_span

logger = logging.getLogger("deliberate_server.api.interrupts")

router = APIRouter(prefix="/interrupts", tags=["interrupts"])

# Default timeout when no policy specifies one
DEFAULT_TIMEOUT_HOURS = 24


class InterruptRequest(BaseModel):
    """Request body for POST /interrupts."""

    thread_id: str
    trace_id: str | None = None
    payload: dict[str, Any]


class InterruptResponse(BaseModel):
    """Response body for POST /interrupts."""

    approval_group_id: str
    approval_ids: list[str]
    approval_mode: str  # "any_of" or "all_of"
    status: str  # "pending" or "auto_approved"
    decision_type: str | None = None  # Populated for auto_approve
    # Backward compat: approval_id is first approval_id (deprecated)
    approval_id: str


@router.post("", response_model=InterruptResponse)
async def submit_interrupt(
    body: InterruptRequest,
    x_deliberate_api_key: str = Header(..., alias="X-Deliberate-API-Key"),
) -> InterruptResponse:
    """Submit a new interrupt from the SDK.

    1. Authenticates via API key
    2. Validates payload against InterruptPayload schema
    3. Evaluates policy → ResolvedPlan
    4. If auto_approve: write ledger entry directly, return immediately
    5. If request_human: create approval row(s), return pending
    """
    # Authenticate: look up application by hashed API key
    async with async_session() as session:
        result = await session.execute(select(Application))
        applications = result.scalars().all()

    app_row: Application | None = None
    for app in applications:
        if verify_api_key(x_deliberate_api_key, app.api_key_hash):
            app_row = app
            break

    if app_row is None:
        raise HTTPException(status_code=401, detail="Invalid API key")

    # Enforce 1MB payload cap (PRD §4.3)
    payload_size = len(_json.dumps(body.payload).encode())
    if payload_size > 1_048_576:
        raise HTTPException(
            status_code=413,
            detail=f"Interrupt payload exceeds 1MB limit ({payload_size} bytes). "
            "Use links to external storage for large artifacts (PRD §4.3).",
        )

    # Validate the payload against InterruptPayload schema
    try:
        validated_payload = InterruptPayload(**body.payload)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Invalid interrupt payload: {e}") from e

    # Evaluate policy
    plan = _evaluate_policy(body.payload)

    now = datetime.now(UTC)
    interrupt_id = uuid.uuid4()

    if plan.action == "auto_approve":
        return await _handle_auto_approve(body, app_row, validated_payload, plan, interrupt_id, now)

    return await _handle_request_human(body, app_row, validated_payload, plan, interrupt_id, now)


def _evaluate_policy(payload: dict[str, Any]) -> ResolvedPlan:
    """Evaluate policy engine, falling back to DEFAULT_APPROVER_EMAIL if needed."""
    try:
        return policy_engine.evaluate(payload)
    except NoMatchingPolicyError:
        if settings.default_approver_email:
            logger.warning(
                "No policy matched interrupt (layout=%s, subject=%s). "
                "Using deprecated DEFAULT_APPROVER_EMAIL=%s as fallback.",
                payload.get("layout"),
                payload.get("subject"),
                settings.default_approver_email,
            )
            return ResolvedPlan(
                action="request_human",
                matched_policy_name="__m1_fallback__",
                matched_rule_name="default_approver_email_env",
                policy_version_hash="sha256:m1-env-fallback",
                approvers=[
                    ResolvedApprover(
                        id="default_approver",
                        email=settings.default_approver_email,
                        display_name=None,
                    )
                ],
                approval_mode="any_of",
                timeout_seconds=DEFAULT_TIMEOUT_HOURS * 3600,
                notify_channels=["email"],
                require_rationale=False,
                on_timeout="fail",
                escalate_to=None,
            )
        raise HTTPException(
            status_code=400,
            detail=f"No policy matched interrupt (layout={payload.get('layout')!r}, "
            f"subject={payload.get('subject')!r}) and no DEFAULT_APPROVER_EMAIL "
            "is configured. Add a policy or set the env var.",
        ) from None


async def _handle_auto_approve(
    body: InterruptRequest,
    app_row: Application,
    validated_payload: InterruptPayload,
    plan: ResolvedPlan,
    interrupt_id: uuid.UUID,
    now: datetime,
) -> InterruptResponse:
    """Auto-approve: write interrupt + ledger entry, no approval row."""
    ledger_id = uuid.uuid4()

    async with async_session() as session, session.begin():
        interrupt_row = Interrupt(
            id=interrupt_id,
            application_id=app_row.id,
            thread_id=body.thread_id,
            trace_id=body.trace_id,
            layout=validated_payload.layout,
            payload=body.payload,
            policy_name=plan.matched_policy_name,
            received_at=now,
        )
        session.add(interrupt_row)
        await session.flush()

        # Get prev_hash for hash chaining
        prev_entry_result = await session.execute(
            select(LedgerEntryModel.content_hash)
            .order_by(LedgerEntryModel.created_at.desc())
            .limit(1)
        )
        prev_hash_value = prev_entry_result.scalar_one_or_none()

        # Build auto-approve ledger content
        ledger_content: dict[str, Any] = {
            "id": str(ledger_id),
            "created_at": now.isoformat(),
            "thread_id": body.thread_id,
            "trace_id": body.trace_id,
            "application_id": app_row.id,
            "interrupt": body.payload,
            "policy_evaluation": {
                "matched_rule": plan.matched_rule_name,
                "policy_name": plan.matched_policy_name,
                "policy_version_hash": plan.policy_version_hash,
            },
            "approval": {
                "approver_id": "system",
                "approver_email": "system",
                "acting_for": None,
                "decided_at": now.isoformat(),
                "decision_type": "auto_approve",
                "decision_payload": None,
                "rationale_category": "auto_approved_by_policy",
                "rationale_notes": plan.rationale,
                "channel": "none",
                "decided_via": "policy_engine",
                "review_duration_ms": 0,
            },
            "escalations": [],
            "prev_hash": prev_hash_value,
            "resume": None,
        }

        content_hash = compute_content_hash(ledger_content)
        content_signature = sign_content_hash(content_hash)
        ledger_content["content_hash"] = content_hash
        ledger_content["signature"] = content_signature

        ledger_entry = LedgerEntryModel(
            id=ledger_id,
            application_id=app_row.id,
            interrupt_id=interrupt_id,
            decision_id=None,
            resume_status="auto_approved",
            resume_latency_ms=0,
            content=ledger_content,
            content_hash=content_hash,
            prev_hash=prev_hash_value,
        )
        session.add(ledger_entry)

    emit_ledger_span(ledger_content)
    INTERRUPTS_TOTAL.labels(layout=validated_payload.layout, action="auto_approve").inc()
    logger.info(
        "Auto-approved interrupt %s (policy=%s, rule=%s, rationale=%s)",
        interrupt_id,
        plan.matched_policy_name,
        plan.matched_rule_name,
        plan.rationale,
    )

    group_id = str(interrupt_id)  # For auto-approve, use interrupt_id as group
    return InterruptResponse(
        approval_group_id=group_id,
        approval_ids=[],
        approval_mode="auto_approve",
        approval_id=group_id,
        status="auto_approved",
        decision_type="auto_approve",
    )


async def _handle_request_human(
    body: InterruptRequest,
    app_row: Application,
    validated_payload: InterruptPayload,
    plan: ResolvedPlan,
    interrupt_id: uuid.UUID,
    now: datetime,
) -> InterruptResponse:
    """Human approval required: create interrupt + approval row(s) with group ID."""
    timeout_delta = timedelta(seconds=plan.timeout_seconds or DEFAULT_TIMEOUT_HOURS * 3600)
    group_id = uuid.uuid4()
    approval_ids: list[uuid.UUID] = []

    async with async_session() as session, session.begin():
        interrupt_row = Interrupt(
            id=interrupt_id,
            application_id=app_row.id,
            thread_id=body.thread_id,
            trace_id=body.trace_id,
            layout=validated_payload.layout,
            payload=body.payload,
            policy_name=plan.matched_policy_name,
            received_at=now,
        )
        session.add(interrupt_row)
        await session.flush()

        if not plan.approvers:
            raise HTTPException(
                status_code=500,
                detail="Policy resolved to request_human but no approvers specified",
            )

        if plan.approval_mode == "any_of":
            # Single approval row — any approver can decide
            aid = uuid.uuid4()
            approval_ids.append(aid)
            session.add(
                Approval(
                    id=aid,
                    interrupt_id=interrupt_id,
                    approver_id=plan.approvers[0].id,
                    acting_for=None,
                    status="pending",
                    timeout_at=now + timeout_delta,
                    escalated_to=None,
                    delegation_reason=None,
                    approval_group_id=group_id,
                    approval_mode="any_of",
                    created_at=now,
                )
            )
        else:
            # all_of: one approval per approver, same group
            for approver in plan.approvers:
                aid = uuid.uuid4()
                approval_ids.append(aid)
                session.add(
                    Approval(
                        id=aid,
                        interrupt_id=interrupt_id,
                        approver_id=approver.id,
                        acting_for=None,
                        status="pending",
                        timeout_at=now + timeout_delta,
                        escalated_to=None,
                        delegation_reason=None,
                        approval_group_id=group_id,
                        approval_mode="all_of",
                        created_at=now,
                    )
                )

    first_approval_id = approval_ids[0]

    # Log approval URLs
    for aid in approval_ids:
        logger.info("[APPROVAL_URL] %s/a/%s", settings.ui_url, aid)
    logger.info(
        "Interrupt %s routed: policy=%s, rule=%s, mode=%s, group=%s, approvers=%s, notify=%s",
        interrupt_id,
        plan.matched_policy_name,
        plan.matched_rule_name,
        plan.approval_mode,
        group_id,
        [a.email for a in plan.approvers],
        plan.notify_channels,
    )

    # Fire notifications
    approval_url = f"{settings.ui_url}/a/{first_approval_id}"
    try:
        results = await notification_dispatcher.dispatch(
            plan=plan,
            approval_id=first_approval_id,
            application_id=app_row.id,
            payload=body.payload,
            approval_url=approval_url,
        )
        if results:
            successes = sum(1 for r in results if r.success)
            logger.info(
                "Notifications dispatched for group %s: %d/%d succeeded",
                group_id,
                successes,
                len(results),
            )
    except Exception:
        logger.exception("Notification dispatch failed for group %s", group_id)

    INTERRUPTS_TOTAL.labels(layout=validated_payload.layout, action="request_human").inc()
    return InterruptResponse(
        approval_group_id=str(group_id),
        approval_ids=[str(a) for a in approval_ids],
        approval_mode=plan.approval_mode,
        approval_id=str(first_approval_id),  # Backward compat
        status="pending",
    )
