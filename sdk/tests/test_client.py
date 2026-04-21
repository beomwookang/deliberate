"""Tests for DeliberateClient against a mocked server.

Covers: happy path, server 500, polling timeout, decision round-trip, group polling.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

import httpx
import pytest

from deliberate.client import DeliberateClient, InterruptResult
from deliberate.types import (
    DeliberateServerError,
    DeliberateTimeoutError,
    InterruptPayload,
)

FAKE_APPROVAL_ID = uuid4()
FAKE_GROUP_ID = uuid4()


def _make_interrupt_response(
    approval_id: str | None = None,
    group_id: str | None = None,
    mode: str = "any_of",
    status: str = "pending",
) -> dict[str, Any]:
    """Build a standard interrupt response with group fields."""
    aid = approval_id or str(FAKE_APPROVAL_ID)
    gid = group_id or str(FAKE_GROUP_ID)
    return {
        "approval_group_id": gid,
        "approval_ids": [aid],
        "approval_mode": mode,
        "approval_id": aid,
        "status": status,
    }


def _make_handler(
    responses: dict[str, Any],
) -> Any:
    """Create an httpx mock transport handler from a dict of path->response mappings."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        for pattern, resp in responses.items():
            if pattern in path:
                if callable(resp):
                    return resp(request)
                status = resp.get("status", 200)
                body = resp.get("body", {})
                return httpx.Response(status, json=body)
        return httpx.Response(404, json={"detail": "not found"})

    return handler


def _make_client(handler: Any) -> DeliberateClient:
    """Create a DeliberateClient with a mock transport."""
    client = DeliberateClient(
        base_url="http://test-server:4000",
        api_key="test-key",
        ui_url="http://test-ui:3000",
    )
    client._http = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://test-server:4000",
        headers={"X-Deliberate-API-Key": "test-key"},
    )
    return client


@pytest.fixture
def payload() -> InterruptPayload:
    return InterruptPayload(
        layout="financial_decision",
        subject="Refund for customer #4821",
        amount={"value": 750.0, "currency": "USD"},  # type: ignore[arg-type]
        customer={"id": "cust_4821", "display_name": "Maya Chen"},
        agent_reasoning="Bug confirmed by engineering.",
        evidence=[{"type": "ticket", "id": "#4821", "summary": "Bug confirmed"}],
    )


# --- Happy path ---


@pytest.mark.asyncio
async def test_submit_interrupt_happy_path(payload: InterruptPayload) -> None:
    handler = _make_handler(
        {
            "/interrupts": {
                "status": 200,
                "body": _make_interrupt_response(),
            }
        }
    )
    client = _make_client(handler)
    result = await client.submit_interrupt(payload=payload, thread_id="thread-123")
    assert isinstance(result, InterruptResult)
    assert result.approval_group_id == FAKE_GROUP_ID
    assert result.approval_id == FAKE_APPROVAL_ID
    assert result.status == "pending"
    assert result.approval_mode == "any_of"
    await client.close()


@pytest.mark.asyncio
async def test_poll_status_pending() -> None:
    handler = _make_handler(
        {
            "/status": {
                "status": 200,
                "body": {"status": "pending", "decision_payload": None},
            }
        }
    )
    client = _make_client(handler)
    result = await client.poll_status(FAKE_APPROVAL_ID)
    assert result is None
    await client.close()


@pytest.mark.asyncio
async def test_poll_status_decided() -> None:
    handler = _make_handler(
        {
            "/status": {
                "status": 200,
                "body": {
                    "status": "decided",
                    "approval_id": str(FAKE_APPROVAL_ID),
                    "decision_type": "approve",
                    "decision_payload": {"amount": 750.0},
                    "rationale_category": "product_issue",
                    "rationale_notes": "Bug confirmed",
                },
            }
        }
    )
    client = _make_client(handler)
    decision = await client.poll_status(FAKE_APPROVAL_ID)
    assert decision is not None
    assert decision.decision_type == "approve"
    assert decision.decision_payload == {"amount": 750.0}
    assert decision.rationale_category == "product_issue"
    assert decision.rationale_notes == "Bug confirmed"
    await client.close()


@pytest.mark.asyncio
async def test_poll_group_status_pending() -> None:
    handler = _make_handler(
        {
            "/approval-groups": {
                "status": 200,
                "body": {
                    "approval_group_id": str(FAKE_GROUP_ID),
                    "approval_mode": "all_of",
                    "status": "pending",
                    "approvals": [],
                },
            }
        }
    )
    client = _make_client(handler)
    result = await client.poll_group_status(FAKE_GROUP_ID)
    assert result is None
    await client.close()


@pytest.mark.asyncio
async def test_poll_group_status_decided() -> None:
    handler = _make_handler(
        {
            "/approval-groups": {
                "status": 200,
                "body": {
                    "approval_group_id": str(FAKE_GROUP_ID),
                    "approval_mode": "all_of",
                    "status": "decided",
                    "approvals": [],
                    "decision_type": "approve",
                    "decision_payload": {"amount": 750.0},
                    "rationale_notes": "Approved by both",
                },
            }
        }
    )
    client = _make_client(handler)
    decision = await client.poll_group_status(FAKE_GROUP_ID)
    assert decision is not None
    assert decision.decision_type == "approve"
    assert decision.decision_payload == {"amount": 750.0}
    await client.close()


@pytest.mark.asyncio
async def test_submit_resume_ack() -> None:
    handler = _make_handler(
        {
            "/resume-ack": {
                "status": 200,
                "body": {"ok": True},
            }
        }
    )
    client = _make_client(handler)
    await client.submit_resume_ack(
        approval_id=FAKE_APPROVAL_ID,
        resume_status="success",
        resume_latency_ms=150,
    )
    await client.close()


# --- Server 500 on submit ---


@pytest.mark.asyncio
async def test_submit_interrupt_server_500(payload: InterruptPayload) -> None:
    handler = _make_handler(
        {
            "/interrupts": {
                "status": 500,
                "body": {"detail": "Internal server error"},
            }
        }
    )
    client = _make_client(handler)
    with pytest.raises(DeliberateServerError) as exc_info:
        await client.submit_interrupt(payload=payload, thread_id="thread-123")
    assert exc_info.value.status_code == 500
    assert "Internal server error" in exc_info.value.detail
    await client.close()


# --- Polling times out client-side ---


@pytest.mark.asyncio
async def test_wait_for_decision_timeout() -> None:
    handler = _make_handler(
        {
            "/status": {
                "status": 200,
                "body": {"status": "pending", "decision_payload": None},
            }
        }
    )
    client = _make_client(handler)
    with pytest.raises(DeliberateTimeoutError) as exc_info:
        await client.wait_for_decision(
            FAKE_APPROVAL_ID,
            timeout_seconds=1,
            poll_interval_seconds=1,
        )
    assert exc_info.value.timeout_seconds == 1
    assert str(FAKE_APPROVAL_ID) in str(exc_info.value)
    await client.close()


@pytest.mark.asyncio
async def test_wait_for_decision_group_timeout() -> None:
    handler = _make_handler(
        {
            "/approval-groups": {
                "status": 200,
                "body": {
                    "approval_group_id": str(FAKE_GROUP_ID),
                    "approval_mode": "all_of",
                    "status": "pending",
                    "approvals": [],
                },
            }
        }
    )
    client = _make_client(handler)
    with pytest.raises(DeliberateTimeoutError):
        await client.wait_for_decision(
            FAKE_GROUP_ID,
            timeout_seconds=1,
            poll_interval_seconds=1,
            use_group=True,
        )
    await client.close()


# --- Decision payload round-trips correctly ---


@pytest.mark.asyncio
async def test_decision_payload_round_trip() -> None:
    """Verify complex decision payloads survive serialization."""
    complex_payload = {
        "amount": 500.0,
        "modified_fields": {"currency": "EUR"},
        "notes": "Approved with modification",
    }
    handler = _make_handler(
        {
            "/status": {
                "status": 200,
                "body": {
                    "status": "decided",
                    "approval_id": str(FAKE_APPROVAL_ID),
                    "decision_type": "modify",
                    "decision_payload": complex_payload,
                    "rationale_category": "policy_exception",
                    "rationale_notes": "One-time exception",
                },
            }
        }
    )
    client = _make_client(handler)
    decision = await client.poll_status(FAKE_APPROVAL_ID)
    assert decision is not None
    assert decision.decision_type == "modify"
    assert decision.decision_payload == complex_payload
    await client.close()


# --- Approval URL construction ---


def test_approval_url() -> None:
    client = DeliberateClient(
        base_url="http://localhost:4000",
        api_key="key",
        ui_url="http://localhost:3000",
    )
    url = client.approval_url(FAKE_APPROVAL_ID)
    assert url == f"http://localhost:3000/a/{FAKE_APPROVAL_ID}"


# --- Submit interrupt sends correct body ---


@pytest.mark.asyncio
async def test_submit_interrupt_sends_correct_body(payload: InterruptPayload) -> None:
    captured_body: dict[str, Any] = {}

    def capture_handler(request: httpx.Request) -> httpx.Response:
        captured_body.update(json.loads(request.content))
        return httpx.Response(
            200,
            json=_make_interrupt_response(),
        )

    handler = _make_handler({"/interrupts": capture_handler})
    client = _make_client(handler)
    await client.submit_interrupt(payload=payload, thread_id="thread-abc", trace_id="trace-xyz")
    assert captured_body["thread_id"] == "thread-abc"
    assert captured_body["trace_id"] == "trace-xyz"
    assert captured_body["payload"]["layout"] == "financial_decision"
    assert captured_body["payload"]["subject"] == "Refund for customer #4821"
    await client.close()
