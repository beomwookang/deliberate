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


class InterruptResult:
    """Result of submitting an interrupt, with group support."""

    def __init__(
        self,
        approval_group_id: UUID,
        approval_ids: list[UUID],
        approval_mode: str,
        status: str,
        decision_type: str | None = None,
    ) -> None:
        self.approval_group_id = approval_group_id
        self.approval_ids = approval_ids
        self.approval_mode = approval_mode
        self.status = status
        self.decision_type = decision_type

    @property
    def approval_id(self) -> UUID:
        """Backward-compat: return first approval_id."""
        if self.approval_ids:
            return self.approval_ids[0]
        return self.approval_group_id


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
        return f"{self.ui_url}/a/{approval_id}"

    async def submit_interrupt(
        self,
        payload: InterruptPayload,
        thread_id: str,
        trace_id: str | None = None,
    ) -> InterruptResult:
        """Submit an interrupt payload to the server.

        Returns InterruptResult with group_id, approval_ids, and mode.

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

        return InterruptResult(
            approval_group_id=UUID(data["approval_group_id"]),
            approval_ids=[UUID(a) for a in data.get("approval_ids", [])],
            approval_mode=data.get("approval_mode", "any_of"),
            status=data["status"],
            decision_type=data.get("decision_type"),
        )

    async def poll_group_status(self, group_id: UUID) -> Decision | None:
        """Poll for a decision on the given approval group.

        Returns None if still pending, or the Decision when the group is resolved.
        Uses GET /approval-groups/{group_id}/status.
        """
        http = self._get_http()
        resp = await http.get(f"/approval-groups/{group_id}/status")
        if resp.status_code != 200:
            detail = resp.text
            with contextlib.suppress(Exception):
                detail = resp.json().get("detail", detail)
            raise DeliberateServerError(resp.status_code, str(detail))
        data = resp.json()
        if data["status"] == "pending":
            return None
        return Decision(
            id=UUID(data["approval_group_id"]),
            decision_type=data.get("decision_type", ""),
            decision_payload=data.get("decision_payload"),
            rationale_notes=data.get("rationale_notes"),
        )

    async def poll_status(self, approval_id: UUID) -> Decision | None:
        """Poll for a decision on a single approval (backward compat).

        Prefer poll_group_status() for new code.
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
        approval_id_or_group_id: UUID,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        poll_interval_seconds: int = DEFAULT_POLL_INTERVAL_SECONDS,
        *,
        use_group: bool = False,
    ) -> Decision:
        """Poll until a decision is made or timeout is reached.

        Args:
            approval_id_or_group_id: The approval or group UUID to poll.
            timeout_seconds: Max seconds to wait.
            poll_interval_seconds: Seconds between polls.
            use_group: If True, poll the group endpoint (for multi-approver).
                       If False, poll the single approval endpoint (backward compat).

        Raises DeliberateTimeoutError if timeout_seconds elapses.
        """
        start = time.monotonic()
        while True:
            if use_group:
                decision = await self.poll_group_status(approval_id_or_group_id)
            else:
                decision = await self.poll_status(approval_id_or_group_id)
            if decision is not None:
                return decision
            elapsed = time.monotonic() - start
            if elapsed + poll_interval_seconds > timeout_seconds:
                raise DeliberateTimeoutError(
                    str(approval_id_or_group_id), timeout_seconds
                )
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
