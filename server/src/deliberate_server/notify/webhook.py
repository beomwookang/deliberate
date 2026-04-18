"""Webhook notification adapter — stub for M3.

POSTs a signed JSON payload to a user-configured URL.
See PRD §6.2 and §6.6 (webhook signing).
"""

from __future__ import annotations

from typing import Any


class WebhookNotifier:
    """Sends approval notifications via outbound webhook."""

    async def send(self, approval_id: str, payload: dict[str, Any], target: str) -> None:
        """POST a signed notification to the configured webhook URL."""
        raise NotImplementedError("WebhookNotifier.send is a stub — implemented in M3")
