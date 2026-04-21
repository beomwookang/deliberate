"""Tests for the webhook notification adapter (Phase 2.3)."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import httpx
import pytest
from deliberate.types import ResolvedApprover

from deliberate_server.notify.base import NotificationContext
from deliberate_server.notify.webhook import WebhookConfig, WebhookNotifier, _sign_payload


def _make_ctx() -> NotificationContext:
    return NotificationContext(
        approval_id=uuid.uuid4(),
        approver=ResolvedApprover(id="test", email="test@acme.com", display_name="Test"),
        layout="financial_decision",
        subject="Refund #123",
        approval_url="http://localhost:3000/a/test-id",
        payload_preview={"subject": "Refund #123", "amount": {"value": 750, "currency": "USD"}},
        expires_at=datetime.now(UTC) + timedelta(hours=4),
    )


class TestSignature:
    def test_sign_payload_deterministic(self) -> None:
        body = b'{"event":"approval.requested"}'
        sig1 = _sign_payload(body, "my-secret")
        sig2 = _sign_payload(body, "my-secret")
        assert sig1 == sig2

    def test_sign_payload_different_secrets(self) -> None:
        body = b'{"event":"approval.requested"}'
        sig1 = _sign_payload(body, "secret-a")
        sig2 = _sign_payload(body, "secret-b")
        assert sig1 != sig2

    def test_sign_payload_matches_manual_hmac(self) -> None:
        body = b'{"test": true}'
        secret = "verify-me"
        expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        assert _sign_payload(body, secret) == expected


class TestWebhookNotifier:
    @pytest.mark.asyncio
    async def test_successful_delivery(self) -> None:
        notifier = WebhookNotifier()
        notifier._configs = [
            WebhookConfig(
                id="test-hook",
                url="http://httpbin.test/post",
                secret_env="TEST_WH_SECRET",
            )
        ]
        ctx = _make_ctx()

        with patch.dict(os.environ, {"TEST_WH_SECRET": "test-secret-123"}):

            async def mock_post(
                url: str,
                content: bytes,
                headers: dict,
            ) -> httpx.Response:
                assert "X-Deliberate-Signature" in headers
                payload = json.loads(content)
                assert payload["event"] == "approval.requested"
                assert payload["approval_id"] == str(ctx.approval_id)
                assert payload["approver"]["email"] == "test@acme.com"
                return httpx.Response(200, text="OK")

            with patch("httpx.AsyncClient.post", side_effect=mock_post):
                result = await notifier.send(ctx)

        assert result.success is True
        assert result.channel == "webhook"

    @pytest.mark.asyncio
    async def test_missing_secret_env(self) -> None:
        notifier = WebhookNotifier()
        notifier._configs = [
            WebhookConfig(id="no-secret", url="http://test/post", secret_env="MISSING_SECRET")
        ]
        ctx = _make_ctx()

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MISSING_SECRET", None)
            result = await notifier.send(ctx)

        assert result.success is False
        assert "not set" in (result.error or "")

    @pytest.mark.asyncio
    async def test_no_configs_returns_success(self) -> None:
        notifier = WebhookNotifier()
        notifier._configs = []
        ctx = _make_ctx()
        result = await notifier.send(ctx)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_4xx_no_retry(self) -> None:
        notifier = WebhookNotifier()
        notifier._configs = [WebhookConfig(id="bad", url="http://test/post", secret_env="WH_SEC")]
        ctx = _make_ctx()
        call_count = 0

        async def mock_post(*args: object, **kwargs: object) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return httpx.Response(400, text="Bad Request")

        with (
            patch.dict(os.environ, {"WH_SEC": "secret"}),
            patch("httpx.AsyncClient.post", side_effect=mock_post),
        ):
            result = await notifier.send(ctx)

        assert result.success is False
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_payload_structure(self) -> None:
        notifier = WebhookNotifier()
        notifier._configs = [
            WebhookConfig(id="struct", url="http://test/post", secret_env="WH_SEC")
        ]
        ctx = _make_ctx()
        captured_payload: dict | None = None

        async def mock_post(url: str, content: bytes, headers: dict) -> httpx.Response:
            nonlocal captured_payload
            captured_payload = json.loads(content)
            return httpx.Response(200, text="OK")

        with (
            patch.dict(os.environ, {"WH_SEC": "secret"}),
            patch("httpx.AsyncClient.post", side_effect=mock_post),
        ):
            await notifier.send(ctx)

        assert captured_payload is not None
        assert captured_payload["event"] == "approval.requested"
        assert captured_payload["deliberate_version"] == "0.2.0"
        assert "approval_id" in captured_payload
        assert captured_payload["layout"] == "financial_decision"
        assert captured_payload["subject"] == "Refund #123"
        assert captured_payload["approval_url"] == ctx.approval_url

    @pytest.mark.asyncio
    async def test_signature_verification(self) -> None:
        """Verify the signature sent matches what the consumer would compute."""
        notifier = WebhookNotifier()
        notifier._configs = [
            WebhookConfig(id="verify", url="http://test/post", secret_env="WH_SEC")
        ]
        ctx = _make_ctx()
        captured_body: bytes | None = None
        captured_sig: str | None = None

        async def mock_post(url: str, content: bytes, headers: dict) -> httpx.Response:
            nonlocal captured_body, captured_sig
            captured_body = content
            captured_sig = headers["X-Deliberate-Signature"]
            return httpx.Response(200)

        secret = "verify-this-secret"
        with (
            patch.dict(os.environ, {"WH_SEC": secret}),
            patch("httpx.AsyncClient.post", side_effect=mock_post),
        ):
            await notifier.send(ctx)

        assert captured_body is not None
        assert captured_sig is not None
        expected = hmac.new(secret.encode(), captured_body, hashlib.sha256).hexdigest()
        assert captured_sig == expected
