"""Tests for the timeout worker (M2b)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from deliberate.types import ResolvedApprover
from httpx import AsyncClient
from sqlalchemy import select

import deliberate_server.db.session as _db_session
from deliberate_server.db.models import Approval, Interrupt
from deliberate_server.db.models import LedgerEntry as LedgerEntryModel
from deliberate_server.policy.types import ResolvedPlan
from deliberate_server.worker import poll_timeouts

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DEFAULT_PAYLOAD: dict[str, Any] = {
    "layout": "financial_decision",
    "subject": "Refund for customer #9999",
    "amount": {"value": 100.0, "currency": "USD"},
    "customer": {"id": "cust_9999", "display_name": "Test User"},
    "agent_reasoning": "Test reasoning.",
    "evidence": [],
}


async def _create_interrupt(application_id: str = "default") -> uuid.UUID:
    interrupt_id = uuid.uuid4()
    async with _db_session.async_session() as session, session.begin():
        session.add(
            Interrupt(
                id=interrupt_id,
                application_id=application_id,
                thread_id="thread-worker-test",
                trace_id=None,
                layout="financial_decision",
                payload=_DEFAULT_PAYLOAD,
                policy_name=None,
                received_at=datetime.now(UTC),
            )
        )
    return interrupt_id


async def _create_approval(
    interrupt_id: uuid.UUID,
    *,
    status: str = "pending",
    timeout_at: datetime | None = None,
    approver_id: str = "approver@test.com",
    approval_group_id: uuid.UUID | None = None,
    approval_mode: str | None = "any_of",
) -> uuid.UUID:
    approval_id = uuid.uuid4()
    if timeout_at is None:
        timeout_at = datetime.now(UTC) - timedelta(minutes=5)  # already expired

    if approval_group_id is None:
        approval_group_id = uuid.uuid4()

    async with _db_session.async_session() as session, session.begin():
        session.add(
            Approval(
                id=approval_id,
                interrupt_id=interrupt_id,
                approver_id=approver_id,
                acting_for=None,
                status=status,
                timeout_at=timeout_at,
                escalated_to=None,
                delegation_reason=None,
                approval_group_id=approval_group_id,
                approval_mode=approval_mode,
                created_at=datetime.now(UTC),
            )
        )
    return approval_id


async def _get_approval(approval_id: uuid.UUID) -> Approval | None:
    async with _db_session.async_session() as session:
        return await session.get(Approval, approval_id)


async def _get_ledger_entries_for_interrupt(interrupt_id: uuid.UUID) -> list[LedgerEntryModel]:
    async with _db_session.async_session() as session:
        result = await session.execute(
            select(LedgerEntryModel).where(LedgerEntryModel.interrupt_id == interrupt_id)
        )
        return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_timeout_fail_marks_approval_timed_out(client: AsyncClient) -> None:
    """Pending approval with expired timeout_at gets marked timed_out with ledger entry."""
    interrupt_id = await _create_interrupt()
    approval_id = await _create_approval(interrupt_id)

    await poll_timeouts()

    approval = await _get_approval(approval_id)
    assert approval is not None
    assert approval.status == "timed_out"

    entries = await _get_ledger_entries_for_interrupt(interrupt_id)
    assert len(entries) == 1
    entry = entries[0]
    assert entry.resume_status == "timed_out"
    assert entry.content["approval"]["decision_type"] == "timeout"
    assert entry.content["approval"]["approver_email"] == "system"
    assert entry.content["approval"]["review_duration_ms"] == 0
    assert entry.content["escalations"] == []


@pytest.mark.asyncio
async def test_timeout_escalate_creates_new_approval(client: AsyncClient) -> None:
    """Approval with escalation policy creates new approval for escalate_to approver."""
    interrupt_id = await _create_interrupt()
    approval_id = await _create_approval(interrupt_id, approver_id="original@test.com")

    escalation_plan = ResolvedPlan(
        action="request_human",
        matched_policy_name="test_policy",
        matched_rule_name="test_rule",
        policy_version_hash="sha256:abc123",
        approvers=[
            ResolvedApprover(id="original@test.com", email="original@test.com", display_name=None)
        ],
        approval_mode="any_of",
        timeout_seconds=3600,
        notify_channels=[],
        on_timeout="escalate",
        escalate_to="escalatee@test.com",
    )

    mock_resolved = [
        ResolvedApprover(id="escalatee@test.com", email="escalatee@test.com", display_name=None)
    ]

    with (
        patch(
            "deliberate_server.worker.policy_engine.evaluate",
            return_value=escalation_plan,
        ),
        patch(
            "deliberate_server.worker.approver_directory.resolve",
            return_value=mock_resolved,
        ),
        patch(
            "deliberate_server.worker.notification_dispatcher.dispatch",
            new_callable=AsyncMock,
            return_value=[],
        ),
    ):
        await poll_timeouts()

    # Original approval should be marked escalated
    original = await _get_approval(approval_id)
    assert original is not None
    assert original.status == "escalated"
    assert original.escalated_to is not None

    # New approval should exist for escalation target
    new_approval_id = original.escalated_to
    new_approval = await _get_approval(new_approval_id)
    assert new_approval is not None
    assert new_approval.status == "pending"
    assert new_approval.approver_id == "escalatee@test.com"
    assert new_approval.interrupt_id == interrupt_id

    # Ledger should record the escalation
    entries = await _get_ledger_entries_for_interrupt(interrupt_id)
    assert len(entries) == 1
    entry = entries[0]
    assert entry.resume_status == "escalated"
    assert len(entry.content["escalations"]) == 1
    esc = entry.content["escalations"][0]
    assert esc["from_approver"] == "original@test.com"
    assert esc["to_approver"] == "escalatee@test.com"
    assert esc["reason"] == "timeout"


@pytest.mark.asyncio
async def test_timeout_escalate_sends_notifications(client: AsyncClient) -> None:
    """Notification dispatcher is called when escalating an approval."""
    interrupt_id = await _create_interrupt()
    await _create_approval(interrupt_id)

    escalation_plan = ResolvedPlan(
        action="request_human",
        matched_policy_name="test_policy",
        matched_rule_name="test_rule",
        policy_version_hash="sha256:abc",
        approvers=[
            ResolvedApprover(id="approver@test.com", email="approver@test.com", display_name=None)
        ],
        approval_mode="any_of",
        timeout_seconds=3600,
        notify_channels=["email"],
        on_timeout="escalate",
        escalate_to="manager@test.com",
    )
    mock_resolved = [
        ResolvedApprover(id="manager@test.com", email="manager@test.com", display_name=None)
    ]

    dispatch_mock = AsyncMock(return_value=[])

    with (
        patch(
            "deliberate_server.worker.policy_engine.evaluate",
            return_value=escalation_plan,
        ),
        patch(
            "deliberate_server.worker.approver_directory.resolve",
            return_value=mock_resolved,
        ),
        patch(
            "deliberate_server.worker.notification_dispatcher.dispatch",
            new_callable=AsyncMock,
            side_effect=dispatch_mock,
        ),
    ):
        await poll_timeouts()

    assert dispatch_mock.called
    call_kwargs = dispatch_mock.call_args.kwargs
    assert call_kwargs["application_id"] == "default"
    assert "approval_url" in call_kwargs


@pytest.mark.asyncio
async def test_no_expired_approvals_noop(client: AsyncClient) -> None:
    """When no approvals have expired, poll_timeouts does nothing."""
    interrupt_id = await _create_interrupt()
    # Timeout in the future — should not be processed
    future_timeout = datetime.now(UTC) + timedelta(hours=2)
    approval_id = await _create_approval(interrupt_id, timeout_at=future_timeout)

    await poll_timeouts()

    approval = await _get_approval(approval_id)
    assert approval is not None
    assert approval.status == "pending"

    entries = await _get_ledger_entries_for_interrupt(interrupt_id)
    assert len(entries) == 0


@pytest.mark.asyncio
async def test_already_decided_not_processed(client: AsyncClient) -> None:
    """Approval with status='decided' is not processed even if timeout_at has passed."""
    interrupt_id = await _create_interrupt()
    # Already decided but timeout in the past
    approval_id = await _create_approval(
        interrupt_id,
        status="decided",
        timeout_at=datetime.now(UTC) - timedelta(hours=1),
    )

    await poll_timeouts()

    # Status should remain decided — the query filters on status='pending'
    approval = await _get_approval(approval_id)
    assert approval is not None
    assert approval.status == "decided"

    entries = await _get_ledger_entries_for_interrupt(interrupt_id)
    assert len(entries) == 0


@pytest.mark.asyncio
async def test_all_of_group_individual_timeout(client: AsyncClient) -> None:
    """In an all_of group, one approval times out while others remain pending.

    The timed-out approval is processed independently; siblings are unaffected.
    """
    interrupt_id = await _create_interrupt()
    group_id = uuid.uuid4()

    # One expired, one not yet expired
    expired_id = await _create_approval(
        interrupt_id,
        timeout_at=datetime.now(UTC) - timedelta(minutes=10),
        approver_id="approver1@test.com",
        approval_group_id=group_id,
        approval_mode="all_of",
    )
    pending_id = await _create_approval(
        interrupt_id,
        timeout_at=datetime.now(UTC) + timedelta(hours=2),
        approver_id="approver2@test.com",
        approval_group_id=group_id,
        approval_mode="all_of",
    )

    await poll_timeouts()

    expired_approval = await _get_approval(expired_id)
    assert expired_approval is not None
    assert expired_approval.status == "timed_out"

    # The non-expired sibling must remain pending
    pending_approval = await _get_approval(pending_id)
    assert pending_approval is not None
    assert pending_approval.status == "pending"

    # Only one ledger entry — for the expired approval
    entries = await _get_ledger_entries_for_interrupt(interrupt_id)
    assert len(entries) == 1
    assert entries[0].resume_status == "timed_out"


@pytest.mark.asyncio
async def test_escalation_depth_limit_falls_back_to_fail(client: AsyncClient) -> None:
    """When max_escalation_depth is reached, _process_timeout_escalate falls back to fail."""
    interrupt_id = await _create_interrupt()
    approval_id = await _create_approval(interrupt_id, approver_id="deep@test.com")

    escalation_plan = ResolvedPlan(
        action="request_human",
        matched_policy_name="test_policy",
        matched_rule_name="test_rule",
        policy_version_hash="sha256:abc",
        approvers=[ResolvedApprover(id="deep@test.com", email="deep@test.com", display_name=None)],
        approval_mode="any_of",
        timeout_seconds=3600,
        notify_channels=[],
        on_timeout="escalate",
        escalate_to="manager@test.com",
    )

    with (
        patch(
            "deliberate_server.worker.policy_engine.evaluate",
            return_value=escalation_plan,
        ),
        patch(
            "deliberate_server.worker._count_escalation_depth",
            new_callable=AsyncMock,
            return_value=3,  # equals default max_escalation_depth of 3
        ),
        patch(
            "deliberate_server.worker.approver_directory.resolve",
        ) as mock_resolve,
    ):
        await poll_timeouts()

    # resolve should NOT have been called — we fell back before reaching it
    mock_resolve.assert_not_called()

    # Approval should be marked timed_out (fail path), not escalated
    approval = await _get_approval(approval_id)
    assert approval is not None
    assert approval.status == "timed_out"

    # Ledger entry should reflect a timeout, not an escalation
    entries = await _get_ledger_entries_for_interrupt(interrupt_id)
    assert len(entries) == 1
    assert entries[0].resume_status == "timed_out"
    assert entries[0].content["approval"]["decision_type"] == "timeout"
    assert entries[0].content["escalations"] == []
