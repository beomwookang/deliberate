"""APScheduler timeout worker entry point.

Polls for pending approvals that have exceeded their timeout_at, and processes
escalation or failure per the matched policy rule. See PRD §6.2 (Timeout Worker).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

import deliberate_server.db.session as _db_session
from deliberate_server.auth import compute_content_hash, sign_content_hash
from deliberate_server.config import settings
from deliberate_server.db.models import Approval, Interrupt
from deliberate_server.db.models import LedgerEntry as LedgerEntryModel
from deliberate_server.metrics import ESCALATIONS_TOTAL, TIMEOUTS_TOTAL
from deliberate_server.notify import notification_dispatcher
from deliberate_server.policy import NoMatchingPolicyError, approver_directory, policy_engine
from deliberate_server.policy.types import ResolvedPlan

logger = logging.getLogger("deliberate_server.worker")


@dataclass(frozen=True)
class _ExpiredApproval:
    """Scalar snapshot of an expired approval — avoids detached ORM instance access."""

    id: uuid.UUID
    interrupt_id: uuid.UUID
    approver_id: str | None
    approval_group_id: uuid.UUID | None
    approval_mode: str | None


async def _count_escalation_depth(approval_id: uuid.UUID) -> int:
    """Count escalation chain depth by following the escalated_to FK chain backwards."""
    depth = 0
    current_id = approval_id
    async with _db_session.async_session() as session:
        while True:
            result = await session.execute(
                select(Approval).where(Approval.escalated_to == current_id)
            )
            parent = result.scalar_one_or_none()
            if parent is None:
                break
            depth += 1
            current_id = parent.id
            if depth > 20:  # Safety cap
                break
    return depth


async def _get_prev_hash() -> str | None:
    """Get the content_hash of the most recent ledger entry for hash chaining."""
    async with _db_session.async_session() as session:
        result = await session.execute(
            select(LedgerEntryModel.content_hash)
            .order_by(LedgerEntryModel.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()


async def _process_timeout_fail(
    snap: _ExpiredApproval,
    interrupt: Interrupt,
    now: datetime,
) -> None:
    """Mark approval timed_out and write a timeout ledger entry."""
    prev_hash = await _get_prev_hash()

    async with _db_session.async_session() as session, session.begin():
        # Re-fetch with FOR UPDATE lock to serialize against decide endpoint
        approval_row = await session.get(Approval, snap.id, with_for_update=True)
        if approval_row is None or approval_row.status != "pending":
            return  # Race condition — already decided or handled

        approval_row.status = "timed_out"

        ledger_id = uuid.uuid4()
        ledger_content: dict[str, Any] = {
            "id": str(ledger_id),
            "created_at": now.isoformat(),
            "thread_id": interrupt.thread_id,
            "trace_id": interrupt.trace_id,
            "application_id": interrupt.application_id,
            "interrupt": interrupt.payload,
            "policy_evaluation": {
                "matched_rule": interrupt.policy_name or "unknown",
                "policy_name": interrupt.policy_name or "unknown",
                "policy_version_hash": "sha256:worker-timeout",
            },
            "approval": {
                "approver_id": snap.approver_id,
                "approver_email": "system",
                "acting_for": None,
                "decided_at": now.isoformat(),
                "decision_type": "timeout",
                "decision_payload": None,
                "rationale_category": "timed_out",
                "rationale_notes": None,
                "channel": "none",
                "decided_via": "timeout_worker",
                "review_duration_ms": 0,
            },
            "approval_group": {
                "group_id": str(snap.approval_group_id) if snap.approval_group_id else None,
                "role": "timed_out",
            },
            "escalations": [],
            "prev_hash": prev_hash,
            "resume": None,
        }

        content_hash = compute_content_hash(ledger_content)
        ledger_content["content_hash"] = content_hash
        ledger_content["signature"] = sign_content_hash(content_hash)

        session.add(
            LedgerEntryModel(
                id=ledger_id,
                application_id=interrupt.application_id,
                interrupt_id=interrupt.id,
                decision_id=None,
                resume_status="timed_out",
                resume_latency_ms=0,
                content=ledger_content,
                content_hash=content_hash,
                prev_hash=prev_hash,
            )
        )

    TIMEOUTS_TOTAL.inc()
    logger.info(
        "Approval %s timed out (interrupt=%s, approver=%s)",
        snap.id,
        interrupt.id,
        snap.approver_id,
    )


async def _process_timeout_escalate(
    snap: _ExpiredApproval,
    interrupt: Interrupt,
    plan: ResolvedPlan,
    now: datetime,
) -> None:
    """Escalate approval: mark original escalated, create new approval for escalate_to."""
    # Check escalation depth guard
    depth = await _count_escalation_depth(snap.id)
    if depth >= settings.max_escalation_depth:
        logger.warning(
            "Escalation depth limit reached (%d >= %d) for approval %s — falling back to fail",
            depth,
            settings.max_escalation_depth,
            snap.id,
        )
        await _process_timeout_fail(snap, interrupt, now)
        return

    escalate_to_ref = plan.escalate_to
    if not escalate_to_ref:
        logger.warning(
            "Approval %s has on_timeout=escalate but no escalate_to — falling back to fail",
            snap.id,
        )
        await _process_timeout_fail(snap, interrupt, now)
        return

    # Resolve the escalation target approver
    try:
        resolved = approver_directory.resolve(escalate_to_ref)
    except Exception:
        logger.warning(
            "Could not resolve escalate_to=%r for approval %s — falling back to fail",
            escalate_to_ref,
            snap.id,
        )
        await _process_timeout_fail(snap, interrupt, now)
        return

    if not resolved:
        logger.warning(
            "escalate_to=%r resolved to empty list for approval %s — falling back to fail",
            escalate_to_ref,
            snap.id,
        )
        await _process_timeout_fail(snap, interrupt, now)
        return

    escalation_target = resolved[0]
    new_approval_id = uuid.uuid4()
    timeout_delta = timedelta(seconds=plan.timeout_seconds or 24 * 3600)
    prev_hash = await _get_prev_hash()

    async with _db_session.async_session() as session, session.begin():
        # Re-fetch with FOR UPDATE lock to serialize against decide endpoint
        approval_row = await session.get(Approval, snap.id, with_for_update=True)
        if approval_row is None or approval_row.status != "pending":
            return  # Race condition — already decided or handled

        # Create new approval for escalation target first (FK requires it to exist)
        new_approval = Approval(
            id=new_approval_id,
            interrupt_id=interrupt.id,
            approver_id=escalation_target.id,
            acting_for=None,
            status="pending",
            timeout_at=now + timeout_delta,
            escalated_to=None,
            delegation_reason=None,
            approval_group_id=snap.approval_group_id,
            approval_mode=snap.approval_mode,
            created_at=now,
        )
        session.add(new_approval)
        await session.flush()  # Ensure new_approval_id exists before FK reference

        # Mark original as escalated
        approval_row.status = "escalated"
        approval_row.escalated_to = new_approval_id

        # Write ledger entry with escalation record
        ledger_id = uuid.uuid4()
        escalation_record = {
            "from_approver": snap.approver_id,
            "to_approver": escalation_target.id,
            "escalated_at": now.isoformat(),
            "reason": "timeout",
        }
        ledger_content: dict[str, Any] = {
            "id": str(ledger_id),
            "created_at": now.isoformat(),
            "thread_id": interrupt.thread_id,
            "trace_id": interrupt.trace_id,
            "application_id": interrupt.application_id,
            "interrupt": interrupt.payload,
            "policy_evaluation": {
                "matched_rule": interrupt.policy_name or "unknown",
                "policy_name": interrupt.policy_name or "unknown",
                "policy_version_hash": "sha256:worker-escalate",
            },
            "approval": {
                "approver_id": snap.approver_id,
                "approver_email": "system",
                "acting_for": None,
                "decided_at": now.isoformat(),
                "decision_type": "escalate",
                "decision_payload": None,
                "rationale_category": "escalated_by_timeout",
                "rationale_notes": f"Escalated to {escalation_target.email} after timeout",
                "channel": "none",
                "decided_via": "timeout_worker",
                "review_duration_ms": 0,
            },
            "approval_group": {
                "group_id": str(snap.approval_group_id) if snap.approval_group_id else None,
                "role": "escalated",
            },
            "escalations": [escalation_record],
            "prev_hash": prev_hash,
            "resume": None,
        }

        content_hash = compute_content_hash(ledger_content)
        ledger_content["content_hash"] = content_hash
        ledger_content["signature"] = sign_content_hash(content_hash)

        session.add(
            LedgerEntryModel(
                id=ledger_id,
                application_id=interrupt.application_id,
                interrupt_id=interrupt.id,
                decision_id=None,
                resume_status="escalated",
                resume_latency_ms=0,
                content=ledger_content,
                content_hash=content_hash,
                prev_hash=prev_hash,
            )
        )

    ESCALATIONS_TOTAL.inc()
    logger.info(
        "Approval %s escalated to %s (new approval=%s, interrupt=%s)",
        snap.id,
        escalation_target.email,
        new_approval_id,
        interrupt.id,
    )

    # Fire notification to escalation target
    escalation_plan = ResolvedPlan(
        action="request_human",
        matched_policy_name=plan.matched_policy_name,
        matched_rule_name=plan.matched_rule_name,
        policy_version_hash=plan.policy_version_hash,
        approvers=[escalation_target],
        approval_mode="any_of",
        timeout_seconds=plan.timeout_seconds,
        notify_channels=plan.notify_channels,
        require_rationale=plan.require_rationale,
        on_timeout=plan.on_timeout,
        escalate_to=plan.escalate_to,
    )
    approval_url = f"{settings.ui_url}/a/{new_approval_id}"
    try:
        await notification_dispatcher.dispatch(
            plan=escalation_plan,
            approval_id=new_approval_id,
            application_id=interrupt.application_id,
            payload=interrupt.payload,
            approval_url=approval_url,
        )
    except Exception:
        logger.exception(
            "Notification failed for escalated approval %s (target=%s)",
            new_approval_id,
            escalation_target.email,
        )


async def _process_timed_out_approval(snap: _ExpiredApproval, now: datetime) -> None:
    """Fetch interrupt, evaluate policy, dispatch timeout action."""
    async with _db_session.async_session() as session:
        interrupt = await session.get(Interrupt, snap.interrupt_id)

    if interrupt is None:
        logger.error(
            "Interrupt %s not found for timed-out approval %s",
            snap.interrupt_id,
            snap.id,
        )
        return

    # Evaluate policy to get on_timeout / escalate_to
    on_timeout = "fail"
    plan: ResolvedPlan | None = None
    try:
        plan = policy_engine.evaluate(interrupt.payload)
        if plan.on_timeout:
            on_timeout = plan.on_timeout
    except NoMatchingPolicyError:
        logger.warning(
            "No policy matched for timed-out approval %s — defaulting to fail",
            snap.id,
        )
    except Exception:
        logger.exception(
            "Policy evaluation error for timed-out approval %s — defaulting to fail",
            snap.id,
        )

    if on_timeout == "escalate" and plan is not None:
        await _process_timeout_escalate(snap, interrupt, plan, now)
    else:
        await _process_timeout_fail(snap, interrupt, now)


async def poll_timeouts() -> None:
    """Poll for pending approvals past their timeout_at and process each one."""
    now = datetime.now(UTC)
    logger.debug("Polling for timed-out approvals at %s", now.isoformat())

    try:
        async with _db_session.async_session() as session:
            result = await session.execute(
                select(Approval).where(
                    Approval.status == "pending",
                    Approval.timeout_at < now,
                )
            )
            # Extract scalar fields before session closes to avoid detached instance errors
            snapshots = [
                _ExpiredApproval(
                    id=row.id,
                    interrupt_id=row.interrupt_id,
                    approver_id=row.approver_id,
                    approval_group_id=row.approval_group_id,
                    approval_mode=row.approval_mode,
                )
                for row in result.scalars().all()
            ]
    except Exception:
        logger.exception("Failed to query timed-out approvals")
        return

    if not snapshots:
        logger.debug("No timed-out approvals found")
        return

    logger.info("Found %d timed-out approval(s) to process", len(snapshots))

    for snap in snapshots:
        try:
            await _process_timed_out_approval(snap, now)
        except Exception:
            logger.exception("Error processing timed-out approval %s", snap.id)


def run() -> None:
    """Entry point for the timeout worker process."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    async def _main() -> None:
        # Initialize policy system before scheduling jobs
        from deliberate_server.policy import init_policy_system

        try:
            init_policy_system()
        except Exception:
            logger.exception("Policy system initialization failed — worker will use fail-default")

        scheduler = AsyncIOScheduler()
        scheduler.add_job(
            poll_timeouts,
            trigger="interval",
            seconds=settings.worker_poll_interval_seconds,
            id="timeout_poller",
            max_instances=1,
            coalesce=True,
        )

        loop = asyncio.get_running_loop()

        def _shutdown(signum: int) -> None:
            logger.info("deliberate-worker: received signal %d, shutting down", signum)
            scheduler.shutdown(wait=False)
            loop.stop()

        loop.add_signal_handler(signal.SIGTERM, _shutdown, signal.SIGTERM)
        loop.add_signal_handler(signal.SIGINT, _shutdown, signal.SIGINT)

        scheduler.start()
        logger.info(
            "deliberate-worker: started (poll_interval=%ds)",
            settings.worker_poll_interval_seconds,
        )

        # Run forever until signal
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.get_event_loop().create_future()

    asyncio.run(_main())


if __name__ == "__main__":
    run()
