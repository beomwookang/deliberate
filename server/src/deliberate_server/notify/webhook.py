"""Webhook notification adapter with HMAC-SHA256 signing (PRD §6.2 Draft v4).

POSTs JSON to all active webhooks in webhooks.yaml with signed payloads.
Retries 3x with exponential backoff on 5xx; no retry on 4xx. Timeout: 10s.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, ClassVar

import httpx
import yaml
from pydantic import BaseModel, Field

from deliberate_server.config import settings
from deliberate_server.notify.base import NotificationContext, NotificationResult

logger = logging.getLogger("deliberate_server.notify.webhook")

MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 2.0
WEBHOOK_TIMEOUT = 10


class WebhookConfig(BaseModel):
    """Configuration for a single webhook destination."""

    id: str
    url: str
    secret_env: str  # env var name holding the webhook secret
    active: bool = True


class WebhooksFileConfig(BaseModel):
    """Top-level structure of webhooks.yaml."""

    webhooks: list[WebhookConfig] = Field(default_factory=list)


def load_webhook_configs() -> list[WebhookConfig]:
    """Load active webhook configurations from webhooks.yaml."""
    path = Path(settings.webhooks_file)
    if not path.exists():
        logger.info("No webhooks.yaml at %s — webhook notifications disabled.", path)
        return []

    try:
        content = path.read_text(encoding="utf-8")
        raw = yaml.safe_load(content)
        if not isinstance(raw, dict):
            logger.warning("webhooks.yaml must be a mapping, got %s", type(raw).__name__)
            return []
        config = WebhooksFileConfig(**raw)
        active = [w for w in config.webhooks if w.active]
        logger.info("Loaded %d active webhooks from %s", len(active), path)
        return active
    except Exception as e:
        logger.error("Failed to load webhooks.yaml: %s", e)
        return []


def _sign_payload(body: bytes, secret: str) -> str:
    """Compute HMAC-SHA256 signature of the request body."""
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


class WebhookNotifier:
    """Sends approval notifications via webhook POST with HMAC signing."""

    channel_name: ClassVar[str] = "webhook"

    def __init__(self) -> None:
        self._configs: list[WebhookConfig] = []

    def load_configs(self) -> None:
        """Load webhook configurations. Called at startup."""
        self._configs = load_webhook_configs()

    async def send(self, ctx: NotificationContext) -> NotificationResult:
        """Send webhook notifications to all active destinations.

        Fans out to all active webhooks — fires to ALL, not just one.
        Returns a single aggregated result.
        """
        if not self._configs:
            return NotificationResult(
                channel=self.channel_name,
                success=True,
                message_id=None,
                error="No active webhooks configured",
                duration_ms=0,
            )

        payload = self._build_payload(ctx)
        body = json.dumps(payload, default=str).encode()

        start = time.monotonic()
        results: list[bool] = []
        errors: list[str] = []

        async with httpx.AsyncClient(timeout=WEBHOOK_TIMEOUT) as client:
            tasks = [
                self._send_to_webhook(client, wh, body)
                for wh in self._configs
            ]
            webhook_results = await asyncio.gather(*tasks)

        for wh, (success, error) in zip(self._configs, webhook_results):
            results.append(success)
            if not success and error:
                errors.append(f"{wh.id}: {error}")

        duration = int((time.monotonic() - start) * 1000)
        all_success = all(results)

        return NotificationResult(
            channel=self.channel_name,
            success=all_success,
            message_id=f"webhooks:{len(results)}",
            error="; ".join(errors) if errors else None,
            duration_ms=duration,
        )

    async def _send_to_webhook(
        self, client: httpx.AsyncClient, wh: WebhookConfig, body: bytes
    ) -> tuple[bool, str | None]:
        """Send to a single webhook with retry logic."""
        secret = os.environ.get(wh.secret_env, "")
        if not secret:
            logger.warning(
                "Webhook '%s' secret env var '%s' is not set — skipping.",
                wh.id,
                wh.secret_env,
            )
            return False, f"Secret env var '{wh.secret_env}' not set"

        signature = _sign_payload(body, secret)
        headers = {
            "Content-Type": "application/json",
            "X-Deliberate-Signature": signature,
            "User-Agent": "Deliberate/0.2.0",
        }

        last_error: str | None = None
        for attempt in range(MAX_RETRIES):
            try:
                resp = await client.post(wh.url, content=body, headers=headers)
                if resp.status_code < 400:
                    logger.info(
                        "Webhook '%s' delivered (status=%d, attempt=%d)",
                        wh.id,
                        resp.status_code,
                        attempt + 1,
                    )
                    return True, None
                if 400 <= resp.status_code < 500:
                    # Client error — don't retry
                    last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
                    logger.warning(
                        "Webhook '%s' returned %d (no retry): %s",
                        wh.id,
                        resp.status_code,
                        resp.text[:200],
                    )
                    return False, last_error
                # 5xx — retry
                last_error = f"HTTP {resp.status_code}"
                logger.warning(
                    "Webhook '%s' returned %d (attempt %d/%d)",
                    wh.id,
                    resp.status_code,
                    attempt + 1,
                    MAX_RETRIES,
                )
            except (httpx.HTTPError, asyncio.TimeoutError) as e:
                last_error = str(e)
                logger.warning(
                    "Webhook '%s' request failed (attempt %d/%d): %s",
                    wh.id,
                    attempt + 1,
                    MAX_RETRIES,
                    e,
                )

            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(RETRY_BACKOFF_BASE ** attempt)

        return False, f"Failed after {MAX_RETRIES} attempts: {last_error}"

    async def health_check(self) -> bool:
        """Check if any webhooks are configured."""
        return len(self._configs) > 0

    def _build_payload(self, ctx: NotificationContext) -> dict[str, Any]:
        """Build the webhook JSON payload."""
        return {
            "event": "approval.requested",
            "deliberate_version": "0.2.0",
            "approval_id": str(ctx.approval_id),
            "approver": {
                "email": ctx.approver.email,
                "display_name": ctx.approver.display_name,
            },
            "layout": ctx.layout,
            "subject": ctx.subject,
            "approval_url": ctx.approval_url,
            "expires_at": ctx.expires_at.isoformat() if ctx.expires_at else None,
            "payload_preview": ctx.payload_preview,
        }
