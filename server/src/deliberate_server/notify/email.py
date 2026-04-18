"""Email notification adapter — stub for M2.

Uses standard SMTP (user-configured). HTML template renders a preview
of the decision plus "Review" button. See PRD §6.2.
"""

from __future__ import annotations

from typing import Any


class EmailNotifier:
    """Sends approval notifications via SMTP email."""

    async def send(self, approval_id: str, payload: dict[str, Any], target: str) -> None:
        """Send an email notification for a pending approval."""
        raise NotImplementedError("EmailNotifier.send is a stub — implemented in M2")
