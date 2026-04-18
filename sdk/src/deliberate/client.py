"""HTTP client for communicating with the Deliberate server.

See PRD §6.4 for the interrupt-to-resume flow.
"""

from __future__ import annotations

from uuid import UUID

from deliberate.types import Decision, InterruptPayload


class DeliberateClient:
    """Client for the Deliberate server API.

    Used by the SDK internally to submit interrupts and poll for decisions.
    Can also be used directly for programmatic access.

    Args:
        base_url: Deliberate server URL (e.g. 'http://localhost:4000').
        api_key: Application API key for authentication.
    """

    def __init__(self, base_url: str, api_key: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    async def submit_interrupt(self, payload: InterruptPayload) -> UUID:
        """Submit an interrupt payload to the server.

        Returns the approval ID for polling.

        See PRD §6.4 step 2: SDK POSTs payload to /interrupts.
        """
        raise NotImplementedError("submit_interrupt is a stub — implemented in M1")

    async def poll_status(self, approval_id: UUID) -> Decision | None:
        """Poll for a decision on the given approval.

        Returns None if still pending, or the Decision when resolved.

        See PRD §6.4 step 4: SDK enters a long-poll loop on /approvals/{id}/status.
        """
        raise NotImplementedError("poll_status is a stub — implemented in M1")

    async def submit_resume_ack(self, approval_id: UUID, status: str) -> None:
        """Acknowledge that the graph has successfully resumed.

        See PRD §6.4 step 7: SDK POSTs resume ACK to close the ledger entry.
        """
        raise NotImplementedError("submit_resume_ack is a stub — implemented in M1")
