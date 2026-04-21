"""Notification protocol and shared types (PRD §6.2 Draft v4).

All notification adapters implement the Notifier protocol.
"""

from __future__ import annotations

from datetime import datetime
from typing import ClassVar, Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel

from deliberate.types import ResolvedApprover


class NotificationContext(BaseModel):
    """Everything a notifier needs to send a notification."""

    approval_id: UUID
    approver: ResolvedApprover  # email + display_name
    layout: str  # for message template selection
    subject: str
    approval_url: str  # the /a/{approval_id} URL
    payload_preview: dict[str, object]  # First ~500 chars of key fields
    expires_at: datetime | None = None  # Reserved for M2b timeout display


class NotificationResult(BaseModel):
    """Result of a single notification attempt."""

    channel: str
    success: bool
    message_id: str | None = None  # Channel-specific tracking ID
    error: str | None = None
    duration_ms: int


@runtime_checkable
class Notifier(Protocol):
    """Protocol that all notification adapters must implement."""

    channel_name: ClassVar[str]

    async def send(self, ctx: NotificationContext) -> NotificationResult: ...

    async def health_check(self) -> bool: ...


def build_payload_preview(payload: dict[str, object], max_chars: int = 500) -> dict[str, object]:
    """Extract a truncated preview of key fields for notification display."""
    preview: dict[str, object] = {}
    total = 0

    # Priority fields for preview
    priority_keys = ["subject", "amount", "customer", "agent_reasoning"]
    for key in priority_keys:
        if key in payload and total < max_chars:
            val = payload[key]
            if isinstance(val, str) and len(val) > 200:
                val = val[:200] + "..."
            elif isinstance(val, dict) and "summary" in val:
                # Structured agent_reasoning — use summary
                summary = val["summary"]
                if isinstance(summary, str) and len(summary) > 200:
                    val = {"summary": summary[:200] + "..."}
                else:
                    val = {"summary": summary}
            preview[key] = val
            total += len(str(val))

    return preview
