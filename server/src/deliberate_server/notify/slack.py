"""Slack notification adapter using slack_sdk (PRD §6.2 Draft v4).

Sends DM to approver via users.lookupByEmail + conversations.open + chat.postMessage.
Block Kit message with "Review and decide" button linking to approval URL.
No inline approve/reject — deferred to v1.2 per PRD §6.5.
"""

from __future__ import annotations

import logging
import time
from functools import lru_cache
from typing import Any, ClassVar

from slack_sdk.errors import SlackApiError
from slack_sdk.web.async_client import AsyncWebClient

from deliberate_server.config import settings
from deliberate_server.notify.base import NotificationContext, NotificationResult

logger = logging.getLogger("deliberate_server.notify.slack")


class SlackNotifier:
    """Sends approval notifications via Slack DM."""

    channel_name: ClassVar[str] = "slack"

    def __init__(self) -> None:
        self._client: AsyncWebClient | None = None
        # Cache email → Slack user ID (expires after 1h via TTL in _lookup_user)
        self._user_cache: dict[str, str | None] = {}
        self._cache_timestamps: dict[str, float] = {}
        self._cache_ttl = 3600  # 1 hour

    def _get_client(self) -> AsyncWebClient | None:
        """Get or create the Slack client. Returns None if not configured."""
        if not settings.slack_bot_token:
            return None
        if self._client is None:
            self._client = AsyncWebClient(token=settings.slack_bot_token)
        return self._client

    async def send(self, ctx: NotificationContext) -> NotificationResult:
        """Send a Slack DM notification for a pending approval."""
        client = self._get_client()
        if client is None:
            return NotificationResult(
                channel=self.channel_name,
                success=False,
                error="SLACK_BOT_TOKEN not configured",
                duration_ms=0,
            )

        start = time.monotonic()

        # Look up Slack user by email
        user_id = await self._lookup_user(client, ctx.approver.email)
        if user_id is None:
            duration = int((time.monotonic() - start) * 1000)
            return NotificationResult(
                channel=self.channel_name,
                success=False,
                error=f"Slack user not found for email: {ctx.approver.email}",
                duration_ms=duration,
            )

        try:
            # Open a DM channel
            dm_resp = await client.conversations_open(users=[user_id])
            if not dm_resp["ok"]:
                raise SlackApiError("conversations.open failed", dm_resp)
            channel_id = dm_resp["channel"]["id"]

            # Send the message with Block Kit
            blocks = self._build_blocks(ctx)
            msg_resp = await client.chat_postMessage(
                channel=channel_id,
                blocks=blocks,
                text=f"Approval needed: {ctx.subject}",  # Fallback for notifications
            )

            duration = int((time.monotonic() - start) * 1000)
            message_ts = msg_resp.get("ts", "")

            logger.info(
                "Slack DM sent to %s (user=%s) for approval %s",
                ctx.approver.email,
                user_id,
                ctx.approval_id,
            )

            return NotificationResult(
                channel=self.channel_name,
                success=True,
                message_id=f"slack:{channel_id}:{message_ts}",
                duration_ms=duration,
            )

        except SlackApiError as e:
            duration = int((time.monotonic() - start) * 1000)
            error_msg = str(e.response.get("error", str(e))) if hasattr(e, "response") else str(e)

            # Rate limit handling
            if hasattr(e, "response") and e.response.get("error") == "ratelimited":
                retry_after = e.response.headers.get("Retry-After", "30")
                logger.warning(
                    "Slack rate limited for %s, retry after %ss",
                    ctx.approver.email,
                    retry_after,
                )
                return NotificationResult(
                    channel=self.channel_name,
                    success=False,
                    error=f"Rate limited (retry after {retry_after}s)",
                    duration_ms=duration,
                )

            logger.error(
                "Slack API error sending DM to %s: %s",
                ctx.approver.email,
                error_msg,
            )
            return NotificationResult(
                channel=self.channel_name,
                success=False,
                error=f"Slack API error: {error_msg}",
                duration_ms=duration,
            )

    async def _lookup_user(self, client: AsyncWebClient, email: str) -> str | None:
        """Look up Slack user ID by email. Cached for 1 hour."""
        now = time.monotonic()

        # Check cache (with TTL)
        if email in self._user_cache:
            cached_at = self._cache_timestamps.get(email, 0)
            if now - cached_at < self._cache_ttl:
                return self._user_cache[email]

        try:
            resp = await client.users_lookupByEmail(email=email)
            if resp["ok"]:
                user_id = resp["user"]["id"]
                self._user_cache[email] = user_id
                self._cache_timestamps[email] = now
                return user_id
            self._user_cache[email] = None
            self._cache_timestamps[email] = now
            return None
        except SlackApiError as e:
            error = e.response.get("error", "") if hasattr(e, "response") else ""
            if error == "users_not_found":
                logger.warning("Slack user not found for email: %s", email)
                self._user_cache[email] = None
                self._cache_timestamps[email] = now
                return None
            # Token invalid or other error — don't cache
            logger.error("Slack users.lookupByEmail failed for %s: %s", email, e)
            return None

    async def health_check(self) -> bool:
        """Check if Slack is configured and the token is valid."""
        client = self._get_client()
        if client is None:
            return False
        try:
            resp = await client.auth_test()
            return resp["ok"]
        except SlackApiError:
            return False

    def _build_blocks(self, ctx: NotificationContext) -> list[dict[str, Any]]:
        """Build Slack Block Kit blocks for the notification."""
        blocks: list[dict[str, Any]] = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "\U0001f514 Approval needed",
                    "emoji": True,
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*{ctx.subject}*",
                },
            },
        ]

        # Add reasoning/evidence preview
        reasoning = ctx.payload_preview.get("agent_reasoning")
        if reasoning:
            if isinstance(reasoning, dict) and "summary" in reasoning:
                text = str(reasoning["summary"])
            elif isinstance(reasoning, str):
                text = reasoning
            else:
                text = None

            if text:
                if len(text) > 300:
                    text = text[:300] + "..."
                blocks.append({
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": text},
                })

        # Amount if present
        amount = ctx.payload_preview.get("amount")
        if isinstance(amount, dict) and "value" in amount:
            currency = amount.get("currency", "USD")
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Amount:* {currency} {amount['value']}",
                },
            })

        # Review button
        blocks.append({
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "Review and decide",
                        "emoji": True,
                    },
                    "url": ctx.approval_url,
                    "style": "primary",
                    "action_id": "review_approval",
                }
            ],
        })

        # Context footer
        approver_name = ctx.approver.display_name or ctx.approver.email
        context_parts = [f"Assigned to {approver_name}"]
        if ctx.expires_at:
            context_parts.append(
                f"Expires {ctx.expires_at.strftime('%Y-%m-%d %H:%M UTC')}"
            )
        blocks.append({
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": " · ".join(context_parts),
                }
            ],
        })

        return blocks
