"""Tests for the notification dispatcher (Phase 2.1)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import ClassVar
from unittest.mock import AsyncMock, patch

import pytest

from deliberate.types import ResolvedApprover
from deliberate_server.notify.base import NotificationContext, NotificationResult
from deliberate_server.notify.dispatcher import NotificationDispatcher
from deliberate_server.policy.types import ResolvedPlan


def _make_ctx(email: str = "test@acme.com") -> NotificationContext:
    return NotificationContext(
        approval_id=uuid.uuid4(),
        approver=ResolvedApprover(id="test", email=email, display_name="Test User"),
        layout="financial_decision",
        subject="Refund for order #123",
        approval_url="http://localhost:3000/a/test-id",
        payload_preview={"subject": "Refund for order #123"},
        expires_at=datetime.now(UTC) + timedelta(hours=4),
    )


def _make_plan(
    approvers: list[ResolvedApprover] | None = None,
    channels: list[str] | None = None,
) -> ResolvedPlan:
    if approvers is None:
        approvers = [ResolvedApprover(id="test", email="test@acme.com", display_name="Test")]
    return ResolvedPlan(
        action="request_human",
        matched_policy_name="test_policy",
        matched_rule_name="test_rule",
        policy_version_hash="abc123",
        approvers=approvers,
        approval_mode="any_of",
        timeout_seconds=14400,
        notify_channels=channels or ["email"],
        require_rationale=False,
    )


class FakeNotifier:
    """Fake notifier for testing — uses 'email' channel name for Pydantic compatibility."""

    channel_name: ClassVar[str] = "email"

    def __init__(self, success: bool = True, channel: str = "email") -> None:
        self._success = success
        self.channel_name = channel  # type: ignore[misc]
        self.send_count = 0

    async def send(self, ctx: NotificationContext) -> NotificationResult:
        self.send_count += 1
        return NotificationResult(
            channel=self.channel_name,
            success=self._success,
            message_id="fake-msg-123" if self._success else None,
            error=None if self._success else "Fake failure",
            duration_ms=10,
        )

    async def health_check(self) -> bool:
        return True


class FakeFailingNotifier:
    """Notifier that raises an exception — uses 'slack' channel name."""

    channel_name: ClassVar[str] = "slack"

    async def send(self, ctx: NotificationContext) -> NotificationResult:
        raise RuntimeError("Simulated adapter crash")

    async def health_check(self) -> bool:
        return False


class TestDispatcher:
    @pytest.mark.asyncio
    async def test_successful_dispatch(self) -> None:
        dispatcher = NotificationDispatcher()
        fake = FakeNotifier(success=True, channel="email")
        dispatcher.register(fake)  # type: ignore[arg-type]

        plan = _make_plan(channels=["email"])

        with patch("deliberate_server.notify.dispatcher.async_session"):
            results = await dispatcher.dispatch(
                plan=plan,
                approval_id=uuid.uuid4(),
                application_id="default",
                payload={"layout": "financial_decision", "subject": "Test"},
                approval_url="http://localhost:3000/a/test",
            )

        assert len(results) == 1
        assert results[0].success is True
        assert fake.send_count == 1

    @pytest.mark.asyncio
    async def test_failing_adapter_returns_result_not_exception(self) -> None:
        dispatcher = NotificationDispatcher()
        failing = FakeFailingNotifier()
        dispatcher.register(failing)  # type: ignore[arg-type]

        plan = _make_plan(channels=["slack"])

        with patch("deliberate_server.notify.dispatcher.async_session"):
            results = await dispatcher.dispatch(
                plan=plan,
                approval_id=uuid.uuid4(),
                application_id="default",
                payload={"layout": "financial_decision", "subject": "Test"},
                approval_url="http://localhost:3000/a/test",
            )

        assert len(results) == 1
        assert results[0].success is False
        assert "Simulated adapter crash" in (results[0].error or "")

    @pytest.mark.asyncio
    async def test_mixed_success_and_failure(self) -> None:
        dispatcher = NotificationDispatcher()
        good = FakeNotifier(success=True, channel="email")
        bad = FakeNotifier(success=False, channel="slack")
        dispatcher.register(good)  # type: ignore[arg-type]
        dispatcher.register(bad)  # type: ignore[arg-type]

        plan = _make_plan(channels=["email", "slack"])

        with patch("deliberate_server.notify.dispatcher.async_session"):
            results = await dispatcher.dispatch(
                plan=plan,
                approval_id=uuid.uuid4(),
                application_id="default",
                payload={"layout": "financial_decision", "subject": "Test"},
                approval_url="http://localhost:3000/a/test",
            )

        assert len(results) == 2
        successes = [r for r in results if r.success]
        failures = [r for r in results if not r.success]
        assert len(successes) == 1
        assert len(failures) == 1

    @pytest.mark.asyncio
    async def test_multiple_approvers_dispatched(self) -> None:
        dispatcher = NotificationDispatcher()
        fake = FakeNotifier(success=True)
        dispatcher.register(fake)  # type: ignore[arg-type]

        approvers = [
            ResolvedApprover(id="a1", email="a@test.com"),
            ResolvedApprover(id="a2", email="b@test.com"),
        ]
        plan = _make_plan(approvers=approvers, channels=["email"])

        with patch("deliberate_server.notify.dispatcher.async_session"):
            results = await dispatcher.dispatch(
                plan=plan,
                approval_id=uuid.uuid4(),
                application_id="default",
                payload={"layout": "financial_decision", "subject": "Test"},
                approval_url="http://localhost:3000/a/test",
            )

        assert len(results) == 2
        assert fake.send_count == 2

    @pytest.mark.asyncio
    async def test_auto_approve_skips_notifications(self) -> None:
        dispatcher = NotificationDispatcher()
        fake = FakeNotifier(success=True)
        dispatcher.register(fake)  # type: ignore[arg-type]

        plan = ResolvedPlan(
            action="auto_approve",
            matched_policy_name="test",
            matched_rule_name="auto",
            policy_version_hash="abc",
        )

        results = await dispatcher.dispatch(
            plan=plan,
            approval_id=uuid.uuid4(),
            application_id="default",
            payload={},
            approval_url="http://localhost:3000/a/test",
        )

        assert results == []
        assert fake.send_count == 0

    @pytest.mark.asyncio
    async def test_unregistered_channel_skipped(self) -> None:
        """Valid channel name in plan, but no adapter registered for it."""
        dispatcher = NotificationDispatcher()
        # Don't register any adapters — webhook channel has no adapter
        plan = _make_plan(channels=["webhook"])

        results = await dispatcher.dispatch(
            plan=plan,
            approval_id=uuid.uuid4(),
            application_id="default",
            payload={"layout": "financial_decision", "subject": "Test"},
            approval_url="http://localhost:3000/a/test",
        )

        assert results == []

    @pytest.mark.asyncio
    async def test_no_channels_configured(self) -> None:
        dispatcher = NotificationDispatcher()
        plan = _make_plan(channels=[])

        results = await dispatcher.dispatch(
            plan=plan,
            approval_id=uuid.uuid4(),
            application_id="default",
            payload={},
            approval_url="http://localhost:3000/a/test",
        )

        assert results == []
