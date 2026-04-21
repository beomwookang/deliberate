"""Approval group status endpoint for multi-approver flows (M2a Fix 3).

GET /approval-groups/{group_id}/status returns the aggregated status:
- any_of: first decision wins, others marked superseded
- all_of: all must decide; aggregate per the rules in _aggregate_decisions()
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from deliberate_server.db.models import Approval, Decision
from deliberate_server.db.session import async_session

logger = logging.getLogger("deliberate_server.api.approval_groups")

router = APIRouter(prefix="/approval-groups", tags=["approval-groups"])


class GroupStatusResponse(BaseModel):
    """Response for GET /approval-groups/{group_id}/status."""

    approval_group_id: str
    approval_mode: str  # any_of, all_of
    status: str  # pending, decided
    # Individual approval statuses
    approvals: list[dict[str, Any]]
    # Populated when status == "decided"
    decision_type: str | None = None
    decision_payload: dict[str, Any] | None = None
    rationale_notes: str | None = None


@router.get("/{group_id}/status", response_model=GroupStatusResponse)
async def get_group_status(group_id: uuid.UUID) -> GroupStatusResponse:
    """Poll for approval group status.

    any_of: decided as soon as any one approval is decided.
    all_of: decided when ALL approvals are decided. Aggregation rules apply.
    """
    async with async_session() as session:
        result = await session.execute(
            select(Approval)
            .where(Approval.approval_group_id == group_id)
            .order_by(Approval.created_at)
        )
        approvals = list(result.scalars().all())

    if not approvals:
        raise HTTPException(status_code=404, detail="Approval group not found")

    mode = approvals[0].approval_mode or "any_of"

    # Fetch decisions for decided approvals
    decided_ids = [a.id for a in approvals if a.status == "decided"]
    decisions_by_approval: dict[uuid.UUID, Decision] = {}
    if decided_ids:
        async with async_session() as session:
            dec_result = await session.execute(
                select(Decision).where(Decision.approval_id.in_(decided_ids))
            )
            for dec_row in dec_result.scalars().all():
                decisions_by_approval[dec_row.approval_id] = dec_row

    # Build individual approval info
    approval_infos = []
    for appr in approvals:
        info: dict[str, Any] = {
            "approval_id": str(appr.id),
            "approver_id": appr.approver_id,
            "status": appr.status,
        }
        if appr.id in decisions_by_approval:
            dec = decisions_by_approval[appr.id]
            info["decision_type"] = dec.decision_type
            info["rationale_notes"] = dec.rationale_notes
        approval_infos.append(info)

    if mode == "any_of":
        return _resolve_any_of(group_id, approvals, decisions_by_approval, approval_infos)
    return _resolve_all_of(group_id, approvals, decisions_by_approval, approval_infos)


def _resolve_any_of(
    group_id: uuid.UUID,
    approvals: list[Approval],
    decisions: dict[uuid.UUID, Decision],
    approval_infos: list[dict[str, Any]],
) -> GroupStatusResponse:
    """any_of: first decision wins."""
    for a in approvals:
        if a.status == "decided" and a.id in decisions:
            d = decisions[a.id]
            return GroupStatusResponse(
                approval_group_id=str(group_id),
                approval_mode="any_of",
                status="decided",
                approvals=approval_infos,
                decision_type=d.decision_type,
                decision_payload=d.decision_payload,
                rationale_notes=d.rationale_notes,
            )

    return GroupStatusResponse(
        approval_group_id=str(group_id),
        approval_mode="any_of",
        status="pending",
        approvals=approval_infos,
    )


def _resolve_all_of(
    group_id: uuid.UUID,
    approvals: list[Approval],
    decisions: dict[uuid.UUID, Decision],
    approval_infos: list[dict[str, Any]],
) -> GroupStatusResponse:
    """all_of: all must decide. Aggregate per rules.

    - Any reject → group decision = reject
    - All approve → group decision = approve, notes aggregated
    - Mix of approve + modify → group decision = modify (most restrictive)
    - Not all decided yet → pending
    """
    all_decided = all(a.status == "decided" for a in approvals)

    # Check for early reject — if any decided approval is a reject, group is decided
    for a in approvals:
        if a.id in decisions:
            d = decisions[a.id]
            if d.decision_type == "reject":
                return GroupStatusResponse(
                    approval_group_id=str(group_id),
                    approval_mode="all_of",
                    status="decided",
                    approvals=approval_infos,
                    decision_type="reject",
                    decision_payload=d.decision_payload,
                    rationale_notes=d.rationale_notes,
                )

    if not all_decided:
        return GroupStatusResponse(
            approval_group_id=str(group_id),
            approval_mode="all_of",
            status="pending",
            approvals=approval_infos,
        )

    # All decided, no rejects — aggregate
    return _aggregate_decisions(group_id, approvals, decisions, approval_infos)


def _aggregate_decisions(
    group_id: uuid.UUID,
    approvals: list[Approval],
    decisions: dict[uuid.UUID, Decision],
    approval_infos: list[dict[str, Any]],
) -> GroupStatusResponse:
    """Aggregate all_of decisions when all approvers have decided.

    Rules:
    - All approve → approve, first approver's payload, notes merged
    - Mix of approve + modify → modify, most restrictive payload
      ("most restrictive" = smallest numeric value in decision_payload)
    """
    decision_list = [decisions[a.id] for a in approvals if a.id in decisions]

    types = {d.decision_type for d in decision_list}
    all_notes = [d.rationale_notes for d in decision_list if d.rationale_notes]
    merged_notes = " | ".join(all_notes) if all_notes else None

    if types == {"approve"}:
        return GroupStatusResponse(
            approval_group_id=str(group_id),
            approval_mode="all_of",
            status="decided",
            approvals=approval_infos,
            decision_type="approve",
            decision_payload=decision_list[0].decision_payload,
            rationale_notes=merged_notes,
        )

    if "modify" in types or types == {"approve", "modify"}:
        # Most restrictive: pick the modify with smallest numeric value
        modify_decisions = [d for d in decision_list if d.decision_type == "modify"]
        if not modify_decisions:
            modify_decisions = decision_list
        most_restrictive = _pick_most_restrictive(modify_decisions)
        return GroupStatusResponse(
            approval_group_id=str(group_id),
            approval_mode="all_of",
            status="decided",
            approvals=approval_infos,
            decision_type="modify",
            decision_payload=most_restrictive.decision_payload,
            rationale_notes=merged_notes,
        )

    # Fallback: use first decision
    first = decision_list[0]
    return GroupStatusResponse(
        approval_group_id=str(group_id),
        approval_mode="all_of",
        status="decided",
        approvals=approval_infos,
        decision_type=first.decision_type,
        decision_payload=first.decision_payload,
        rationale_notes=merged_notes,
    )


def _pick_most_restrictive(decisions: list[Decision]) -> Decision:
    """Pick the decision with the smallest numeric value in payload.

    "Most restrictive" for M2a means smallest numeric value.
    M3 can make this user-configurable per policy.
    """
    best = decisions[0]
    best_val = _extract_numeric(best.decision_payload)

    for d in decisions[1:]:
        val = _extract_numeric(d.decision_payload)
        if val is not None and (best_val is None or val < best_val):
            best = d
            best_val = val

    return best


def _extract_numeric(payload: dict[str, Any] | None) -> float | None:
    """Extract the first numeric value from a decision payload."""
    if not payload:
        return None
    for v in payload.values():
        if isinstance(v, int | float):
            return float(v)
        if isinstance(v, dict):
            for inner in v.values():
                if isinstance(inner, int | float):
                    return float(inner)
    return None
