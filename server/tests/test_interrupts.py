"""Tests for POST /interrupts endpoint."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

VALID_PAYLOAD = {
    "thread_id": "thread-123",
    "trace_id": "trace-456",
    "payload": {
        "layout": "financial_decision",
        "subject": "Refund for customer #4821",
        "amount": {"value": 750.0, "currency": "USD"},
        "customer": {"id": "cust_4821", "display_name": "Maya Chen"},
        "agent_reasoning": "Bug confirmed by engineering.",
        "evidence": [{"type": "ticket", "id": "#4821", "summary": "Bug confirmed"}],
    },
}

API_KEY_HEADER = {"X-Deliberate-API-Key": "test-api-key"}


@pytest.mark.asyncio
async def test_submit_interrupt_valid(client: AsyncClient) -> None:
    resp = await client.post("/interrupts", json=VALID_PAYLOAD, headers=API_KEY_HEADER)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "pending"
    assert "approval_id" in data
    # approval_id should be a valid UUID string
    import uuid

    uuid.UUID(data["approval_id"])


@pytest.mark.asyncio
async def test_submit_interrupt_missing_api_key(client: AsyncClient) -> None:
    resp = await client.post("/interrupts", json=VALID_PAYLOAD)
    assert resp.status_code == 422  # FastAPI validation — header required


@pytest.mark.asyncio
async def test_submit_interrupt_wrong_api_key(client: AsyncClient) -> None:
    resp = await client.post(
        "/interrupts",
        json=VALID_PAYLOAD,
        headers={"X-Deliberate-API-Key": "wrong-key"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_submit_interrupt_malformed_payload(client: AsyncClient) -> None:
    bad_payload = {
        "thread_id": "thread-123",
        "payload": {"not_a_valid_field": True},  # missing layout and subject
    }
    resp = await client.post("/interrupts", json=bad_payload, headers=API_KEY_HEADER)
    assert resp.status_code == 422
