"""Adversarial tests for notification dispatcher (M2a Validation Part C)."""

from __future__ import annotations

import hashlib
import hmac
import os
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from deliberate.types import ResolvedApprover

from deliberate_server.notify.base import NotificationContext
from deliberate_server.notify.webhook import WebhookConfig, WebhookNotifier
from deliberate_server.policy.types import ResolvedPlan


def _ctx(email: str = "test@acme.com") -> NotificationContext:
    return NotificationContext(
        approval_id=uuid.uuid4(),
        approver=ResolvedApprover(id="test", email=email),
        layout="financial_decision",
        subject="Test",
        approval_url="http://localhost:3000/a/test",
        payload_preview={"subject": "Test"},
        expires_at=datetime.now(UTC) + timedelta(hours=4),
    )


def _plan(channels: list[str], approvers: list[ResolvedApprover] | None = None) -> ResolvedPlan:
    if approvers is None:
        approvers = [ResolvedApprover(id="t", email="t@acme.com")]
    return ResolvedPlan(
        action="request_human",
        matched_policy_name="test",
        matched_rule_name="test",
        policy_version_hash="abc",
        approvers=approvers,
        approval_mode="any_of",
        timeout_seconds=14400,
        notify_channels=channels,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# C2 — Webhook retry behavior
# ---------------------------------------------------------------------------


class TestC2WebhookRetry:
    @pytest.mark.asyncio
    async def test_5xx_retries_then_fails(self) -> None:
        """500 permanently → 3 attempts then give up."""
        notifier = WebhookNotifier()
        notifier._configs = [WebhookConfig(id="retry", url="http://test/post", secret_env="SEC")]
        call_count = 0

        async def mock_post(*a: object, **kw: object) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return httpx.Response(500, text="Internal Server Error")

        with (
            patch.dict(os.environ, {"SEC": "secret"}),
            patch("httpx.AsyncClient.post", side_effect=mock_post),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await notifier.send(_ctx())

        assert result.success is False
        assert call_count == 3  # MAX_RETRIES

    @pytest.mark.asyncio
    async def test_4xx_no_retry(self) -> None:
        notifier = WebhookNotifier()
        notifier._configs = [WebhookConfig(id="noretry", url="http://test/post", secret_env="SEC")]
        call_count = 0

        async def mock_post(*a: object, **kw: object) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return httpx.Response(403, text="Forbidden")

        with (
            patch.dict(os.environ, {"SEC": "secret"}),
            patch("httpx.AsyncClient.post", side_effect=mock_post),
        ):
            result = await notifier.send(_ctx())

        assert result.success is False
        assert call_count == 1  # No retry on 4xx

    @pytest.mark.asyncio
    async def test_connection_error_retries(self) -> None:
        notifier = WebhookNotifier()
        notifier._configs = [WebhookConfig(id="connerr", url="http://test/post", secret_env="SEC")]
        call_count = 0

        async def mock_post(*a: object, **kw: object) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            raise httpx.ConnectError("Connection refused")

        with (
            patch.dict(os.environ, {"SEC": "secret"}),
            patch("httpx.AsyncClient.post", side_effect=mock_post),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await notifier.send(_ctx())

        assert result.success is False
        assert call_count == 3  # Retried


# ---------------------------------------------------------------------------
# C4 — Secret leakage checks
# ---------------------------------------------------------------------------


class TestC4SecretLeakage:
    """Grep the source code for secret logging. Static analysis."""

    def test_no_smtp_password_logged(self) -> None:
        """Check email.py doesn't log the password."""
        import inspect

        import deliberate_server.notify.email as mod

        source = inspect.getsource(mod)
        assert "smtp_password" not in source.lower().replace("settings.smtp_password", "").replace(
            "smtp_password", ""
        ).replace("SMTP_PASSWORD", "")
        # More targeted: password should only appear in aiosmtplib.send() call
        lines = source.split("\n")
        for i, line in enumerate(lines):
            if "password" in line.lower() and "logger" in line.lower():
                pytest.fail(f"Potential secret leak at email.py line {i + 1}: {line.strip()}")

    def test_no_slack_token_logged(self) -> None:
        import inspect

        import deliberate_server.notify.slack as mod

        source = inspect.getsource(mod)
        lines = source.split("\n")
        for i, line in enumerate(lines):
            if "bot_token" in line.lower() and "logger" in line.lower():
                pytest.fail(f"Potential token leak at slack.py line {i + 1}: {line.strip()}")

    def test_no_webhook_secret_logged(self) -> None:
        import inspect

        import deliberate_server.notify.webhook as mod

        source = inspect.getsource(mod)
        lines = source.split("\n")
        for i, line in enumerate(lines):
            if "secret" in line.lower() and "logger" in line.lower():
                # Allow: "secret env var 'X' is not set" — that's the env var NAME, not value
                if "not set" in line.lower() or "secret_env" in line:
                    continue
                pytest.fail(f"Potential secret leak at webhook.py line {i + 1}: {line.strip()}")


# ---------------------------------------------------------------------------
# C5 — Webhook signature verifiability (independent verification)
# ---------------------------------------------------------------------------


class TestC5SignatureVerification:
    @pytest.mark.asyncio
    async def test_consumer_can_verify_signature(self) -> None:
        """Independently compute HMAC and verify it matches the header."""
        notifier = WebhookNotifier()
        notifier._configs = [WebhookConfig(id="sig", url="http://test/post", secret_env="SIG_SEC")]
        captured: dict = {}

        async def mock_post(url: str, content: bytes, headers: dict) -> httpx.Response:
            captured["body"] = content
            captured["signature"] = headers.get("X-Deliberate-Signature", "")
            return httpx.Response(200)

        secret = "my-webhook-secret-2024"
        with (
            patch.dict(os.environ, {"SIG_SEC": secret}),
            patch("httpx.AsyncClient.post", side_effect=mock_post),
        ):
            await notifier.send(_ctx())

        # Independent verification
        body = captured["body"]
        expected_sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        assert captured["signature"] == expected_sig

        # Verify it's hex (not base64, no prefix)
        assert all(c in "0123456789abcdef" for c in captured["signature"])
        assert len(captured["signature"]) == 64  # SHA-256 hex

    @pytest.mark.asyncio
    async def test_wrong_secret_fails_verification(self) -> None:
        notifier = WebhookNotifier()
        notifier._configs = [
            WebhookConfig(id="wrong", url="http://test/post", secret_env="SIG_SEC")
        ]
        captured: dict = {}

        async def mock_post(url: str, content: bytes, headers: dict) -> httpx.Response:
            captured["body"] = content
            captured["signature"] = headers.get("X-Deliberate-Signature", "")
            return httpx.Response(200)

        with (
            patch.dict(os.environ, {"SIG_SEC": "correct-secret"}),
            patch("httpx.AsyncClient.post", side_effect=mock_post),
        ):
            await notifier.send(_ctx())

        wrong_sig = hmac.new(b"wrong-secret", captured["body"], hashlib.sha256).hexdigest()
        assert captured["signature"] != wrong_sig
