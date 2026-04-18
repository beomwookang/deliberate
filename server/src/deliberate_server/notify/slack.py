"""Slack notification adapter — stub for M2.

Uses Bolt SDK to send DM or channel message with a "Review" button
linking to the approval URL. See PRD §6.2 (Notification Dispatcher).
"""

from __future__ import annotations

from typing import Any


class SlackNotifier:
    """Sends approval notifications via Slack."""

    async def send(self, approval_id: str, payload: dict[str, Any], target: str) -> None:
        """Send a Slack notification for a pending approval."""
        raise NotImplementedError("SlackNotifier.send is a stub — implemented in M2")
