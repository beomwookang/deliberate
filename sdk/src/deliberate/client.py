"""HTTP client for communicating with the Deliberate server.

See PRD §6.4 for the interrupt-to-resume flow.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import time
from uuid import UUID

import httpx

from deliberate.types import (
    Decision,
    DeliberateServerError,
    DeliberateTimeoutError,
    InterruptPayload,
)

logger = logging.getLogger("deliberate.client")

DEFAULT_POLL_INTERVAL_SECONDS = 2
DEFAULT_TIMEOUT_SECONDS = 3600  # 1 hour


class DeliberateClient:
    """Client for the Deliberate server API.

    Used by the SDK internally to submit interrupts and poll for decisions.
    Can also be used directly for programmatic access.

    Args:
        base_url: Deliberate server URL (e.g. 'http://localhost:4000').
        api_key: Application API key for authentication.
        ui_url: Deliberate UI URL for constructing approval links.
            Defaults to DELIBERATE_UI_URL env var or 'http://localhost:3000'.
    """

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        ui_url: str | None = None,
    ) -> None:
        self.base_url = (
            base_url or os.environ.get("DELIBERATE_SERVER_URL", "http://localhost:4000")
        ).rstrip("/")
        self.api_key = api_key or os.environ.get("DELIBERATE_API_KEY", "")
        self.ui_url = (
            ui_url or os.environ.get("DELIBERATE_UI_URL", "http://localhost:3000")
        ).rstrip("/")
        self._http: httpx.AsyncClient | None = None

    def _get_http(self) -> httpx.AsyncClient:
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(
                base_url=self.base_url,
                headers={"X-Deliberate-API-Key": self.api_key},
                timeout=30.0,
            )
        return self._http

    async def close(self) -> None:
        if self._http is not None and not self._http.is_closed:
            await self._http.aclose()
            self._http = None

    def approval_url(self, approval_id: UUID) -> str:
        """Construct the approval URL for a given approval ID."""
        # TODO(M2): Replace with signed token per PRD §6.6
        return f"{self.ui_url}/a/{approval_id}"

    async def submit_interrupt(
        self,
        payload: InterruptPayload,
        thread_id: str,
        trace_id: str | None = None,
    ) -> tuple[UUID, str]:
        """Submit an interrupt payload to the server.

        Returns (approval_id, status).

        See PRD §6.4 step 2: SDK POSTs payload to /interrupts.
        """
        http = self._get_http()
        body = {
            "thread_id": thread_id,
            "trace_id": trace_id,
            "payload": payload.model_dump(mode="json"),
        }
        resp = await http.post("/interrupts", json=body)
        if resp.status_code != 200:
            detail = resp.text
            with contextlib.suppress(Exception):
                detail = resp.json().get("detail", detail)
            raise DeliberateServerError(resp.status_code, str(detail))
        data = resp.json()
        approval_id = UUID(data["approval_id"])
        return approval_id, data["status"]

    async def poll_status(self, approval_id: UUID) -> Decision | None:
        """Poll for a decision on the given approval.

        Returns None if still pending, or the Decision when resolved.

        See PRD §6.4 step 4: SDK enters a long-poll loop on /approvals/{id}/status.
        """
        http = self._get_http()
        resp = await http.get(f"/approvals/{approval_id}/status")
        if resp.status_code != 200:
            detail = resp.text
            with contextlib.suppress(Exception):
                detail = resp.json().get("detail", detail)
            raise DeliberateServerError(resp.status_code, str(detail))
        data = resp.json()
        if data["status"] == "pending":
            return None
        return Decision(
            id=UUID(data["approval_id"]) if "approval_id" in data else approval_id,
            decision_type=data["decision_type"],
            decision_payload=data.get("decision_payload"),
            rationale_category=data.get("rationale_category"),
            rationale_notes=data.get("rationale_notes"),
        )

    async def wait_for_decision(
        self,
        approval_id: UUID,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        poll_interval_seconds: int = DEFAULT_POLL_INTERVAL_SECONDS,
    ) -> Decision:
        """Poll until a decision is made or timeout is reached.

        Raises DeliberateTimeoutError if timeout_seconds elapses.
        """
        start = time.monotonic()
        while True:
            decision = await self.poll_status(approval_id)
            if decision is not None:
                return decision
            elapsed = time.monotonic() - start
            if elapsed + poll_interval_seconds > timeout_seconds:
                raise DeliberateTimeoutError(str(approval_id), timeout_seconds)
            await asyncio.sleep(poll_interval_seconds)

    async def submit_resume_ack(
        self,
        approval_id: UUID,
        resume_status: str,
        resume_latency_ms: int,
    ) -> None:
        """Acknowledge that the graph has successfully resumed.

        See PRD §6.4 step 7: SDK POSTs resume ACK to close the ledger entry.
        """
        http = self._get_http()
        body = {
            "resume_status": resume_status,
            "resume_latency_ms": resume_latency_ms,
        }
        resp = await http.post(f"/approvals/{approval_id}/resume-ack", json=body)
        if resp.status_code != 200:
            detail = resp.text
            with contextlib.suppress(Exception):
                detail = resp.json().get("detail", detail)
            raise DeliberateServerError(resp.status_code, str(detail))
