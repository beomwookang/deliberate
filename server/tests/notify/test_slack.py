"""Tests for the Slack notification adapter (Phase 2.4).

Uses mocked Slack API responses — no real Slack calls.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from deliberate.types import ResolvedApprover
from deliberate_server.notify.base import NotificationContext
from deliberate_server.notify.slack import SlackNotifier


def _make_ctx(email: str = "priya@acme.com") -> NotificationContext:
    return NotificationContext(
        approval_id=uuid.uuid4(),
        approver=ResolvedApprover(id="finance_lead", email=email, display_name="Priya Sharma"),
        layout="financial_decision",
        subject="Refund for order #123",
        approval_url="http://localhost:3000/a/test-id",
        payload_preview={
            "subject": "Refund for order #123",
            "amount": {"value": 750, "currency": "USD"},
            "agent_reasoning": {"summary": "Bug confirmed by engineering"},
        },
        expires_at=datetime.now(UTC) + timedelta(hours=4),
    )


class TestSlackNotifier:
    @pytest.mark.asyncio
    async def test_no_token_returns_failure(self) -> None:
        notifier = SlackNotifier()
        with patch("deliberate_server.notify.slack.settings") as mock_settings:
            mock_settings.slack_bot_token = ""
            result = await notifier.send(_make_ctx())

        assert result.success is False
        assert "not configured" in (result.error or "")

    @pytest.mark.asyncio
    async def test_user_found_dm_sent(self) -> None:
        notifier = SlackNotifier()
        mock_client = AsyncMock()

        # Mock users.lookupByEmail
        mock_client.users_lookupByEmail = AsyncMock(return_value={
            "ok": True,
            "user": {"id": "U12345"},
        })

        # Mock conversations.open
        mock_client.conversations_open = AsyncMock(return_value={
            "ok": True,
            "channel": {"id": "D67890"},
        })

        # Mock chat.postMessage
        mock_client.chat_postMessage = AsyncMock(return_value={
            "ok": True,
            "ts": "1234567890.123456",
        })

        notifier._client = mock_client
        with patch("deliberate_server.notify.slack.settings") as mock_settings:
            mock_settings.slack_bot_token = "xoxb-test-token"
            result = await notifier.send(_make_ctx())

        assert result.success is True
        assert result.message_id is not None
        assert "slack:" in result.message_id

        # Verify the API was called correctly
        mock_client.users_lookupByEmail.assert_called_once_with(email="priya@acme.com")
        mock_client.conversations_open.assert_called_once_with(users=["U12345"])
        mock_client.chat_postMessage.assert_called_once()

        # Verify blocks structure
        call_kwargs = mock_client.chat_postMessage.call_args[1]
        assert call_kwargs["channel"] == "D67890"
        blocks = call_kwargs["blocks"]
        assert any(b.get("type") == "header" for b in blocks)
        assert any(b.get("type") == "actions" for b in blocks)

    @pytest.mark.asyncio
    async def test_user_not_found_graceful_failure(self) -> None:
        from slack_sdk.errors import SlackApiError

        notifier = SlackNotifier()
        mock_client = AsyncMock()

        error_response = MagicMock()
        error_response.get.return_value = "users_not_found"
        error_response.__getitem__ = lambda self, key: {"error": "users_not_found"}[key]

        mock_client.users_lookupByEmail = AsyncMock(
            side_effect=SlackApiError("users_not_found", error_response)
        )

        notifier._client = mock_client
        with patch("deliberate_server.notify.slack.settings") as mock_settings:
            mock_settings.slack_bot_token = "xoxb-test-token"
            result = await notifier.send(_make_ctx())

        assert result.success is False
        assert "not found" in (result.error or "")
        # Should NOT have tried to send a message
        mock_client.conversations_open.assert_not_called()

    @pytest.mark.asyncio
    async def test_user_cache_hit(self) -> None:
        notifier = SlackNotifier()
        mock_client = AsyncMock()

        mock_client.users_lookupByEmail = AsyncMock(return_value={
            "ok": True,
            "user": {"id": "U12345"},
        })
        mock_client.conversations_open = AsyncMock(return_value={
            "ok": True,
            "channel": {"id": "D67890"},
        })
        mock_client.chat_postMessage = AsyncMock(return_value={"ok": True, "ts": "123"})

        notifier._client = mock_client
        with patch("deliberate_server.notify.slack.settings") as mock_settings:
            mock_settings.slack_bot_token = "xoxb-test-token"
            # First call
            await notifier.send(_make_ctx())
            # Second call — should use cache
            await notifier.send(_make_ctx())

        # lookupByEmail should only be called once (cached)
        assert mock_client.users_lookupByEmail.call_count == 1
        # But messages should be sent twice
        assert mock_client.chat_postMessage.call_count == 2

    @pytest.mark.asyncio
    async def test_token_invalid_graceful_failure(self) -> None:
        from slack_sdk.errors import SlackApiError

        notifier = SlackNotifier()
        mock_client = AsyncMock()

        error_response = MagicMock()
        error_response.get.return_value = "invalid_auth"

        mock_client.users_lookupByEmail = AsyncMock(
            side_effect=SlackApiError("invalid_auth", error_response)
        )

        notifier._client = mock_client
        with patch("deliberate_server.notify.slack.settings") as mock_settings:
            mock_settings.slack_bot_token = "xoxb-bad-token"
            result = await notifier.send(_make_ctx())

        assert result.success is False

    @pytest.mark.asyncio
    async def test_block_kit_structure(self) -> None:
        """Verify the Block Kit message has required structure."""
        notifier = SlackNotifier()
        ctx = _make_ctx()
        blocks = notifier._build_blocks(ctx)

        # Should have: header, subject section, reasoning, amount, actions, context
        block_types = [b["type"] for b in blocks]
        assert "header" in block_types
        assert "actions" in block_types
        assert "context" in block_types

        # Check the button URL
        actions_block = next(b for b in blocks if b["type"] == "actions")
        button = actions_block["elements"][0]
        assert button["url"] == ctx.approval_url
        assert button["style"] == "primary"

    @pytest.mark.asyncio
    async def test_health_check_no_token(self) -> None:
        notifier = SlackNotifier()
        with patch("deliberate_server.notify.slack.settings") as mock_settings:
            mock_settings.slack_bot_token = ""
            result = await notifier.health_check()
        assert result is False
