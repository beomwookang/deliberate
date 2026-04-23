"""Tests for approval endpoints: status, payload, decide, resume-ack, and ledger."""

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
        "agent_reasoning": "Bug confirmed.",
        "evidence": [{"type": "ticket", "id": "#4821", "summary": "Bug confirmed"}],
    },
}

API_KEY_HEADER = {"X-Deliberate-API-Key": "test-api-key"}


async def _create_interrupt(client: AsyncClient) -> str:
    """Helper: create an interrupt and return the approval_id."""
    resp = await client.post("/interrupts", json=VALID_PAYLOAD, headers=API_KEY_HEADER)
    assert resp.status_code == 200
    return resp.json()["approval_id"]


# --- Status polling ---


@pytest.mark.asyncio
async def test_status_pending(client: AsyncClient) -> None:
    approval_id = await _create_interrupt(client)
    resp = await client.get(f"/approvals/{approval_id}/status", headers=API_KEY_HEADER)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "pending"
    assert data["decision_type"] is None


@pytest.mark.asyncio
async def test_status_not_found(client: AsyncClient) -> None:
    fake_id = "00000000-0000-0000-0000-000000000001"
    resp = await client.get(f"/approvals/{fake_id}/status", headers=API_KEY_HEADER)
    assert resp.status_code == 404


# --- Payload fetch ---


@pytest.mark.asyncio
async def test_payload_fetch(client: AsyncClient) -> None:
    approval_id = await _create_interrupt(client)
    resp = await client.get(f"/approvals/{approval_id}/payload", headers=API_KEY_HEADER)
    assert resp.status_code == 200
    data = resp.json()
    assert data["layout"] == "financial_decision"
    assert data["payload"]["subject"] == "Refund for customer #4821"
    assert data["status"] == "pending"


# --- Decision submission ---


@pytest.mark.asyncio
async def test_decide_happy_path(client: AsyncClient) -> None:
    approval_id = await _create_interrupt(client)

    decide_body = {
        "decision_type": "approve",
        "decision_payload": {"amount": 750.0},
        "rationale_category": "product_issue",
        "rationale_notes": "Bug confirmed, one-time exception",
        "approver_email": "approver@test.com",
        "review_duration_ms": 5000,
        "decided_via": "web_ui",
    }
    resp = await client.post(f"/approvals/{approval_id}/decide", json=decide_body)
    assert resp.status_code == 200
    assert resp.json()["status"] == "decided"

    # Status should now be decided
    resp = await client.get(f"/approvals/{approval_id}/status", headers=API_KEY_HEADER)
    data = resp.json()
    assert data["status"] == "decided"
    assert data["decision_type"] == "approve"
    assert data["decision_payload"] == {"amount": 750.0}


@pytest.mark.asyncio
async def test_decide_already_decided(client: AsyncClient) -> None:
    approval_id = await _create_interrupt(client)

    decide_body = {
        "decision_type": "approve",
        "approver_email": "approver@test.com",
        "decided_via": "web_ui",
    }
    resp = await client.post(f"/approvals/{approval_id}/decide", json=decide_body)
    assert resp.status_code == 200

    # Try to decide again
    resp = await client.post(f"/approvals/{approval_id}/decide", json=decide_body)
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_decide_not_found(client: AsyncClient) -> None:
    fake_id = "00000000-0000-0000-0000-000000000001"
    decide_body = {
        "decision_type": "approve",
        "approver_email": "approver@test.com",
        "decided_via": "web_ui",
    }
    resp = await client.post(f"/approvals/{fake_id}/decide", json=decide_body)
    assert resp.status_code == 404


# --- Resume ACK ---


@pytest.mark.asyncio
async def test_resume_ack(client: AsyncClient) -> None:
    approval_id = await _create_interrupt(client)

    # Decide first
    decide_body = {
        "decision_type": "approve",
        "approver_email": "approver@test.com",
        "decided_via": "web_ui",
    }
    resp = await client.post(f"/approvals/{approval_id}/decide", json=decide_body)
    assert resp.status_code == 200

    # Send resume ACK
    ack_body = {"resume_status": "success", "resume_latency_ms": 150}
    resp = await client.post(f"/approvals/{approval_id}/resume-ack", json=ack_body)
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


# --- Ledger query ---


@pytest.mark.asyncio
async def test_ledger_query_by_thread_id(client: AsyncClient) -> None:
    approval_id = await _create_interrupt(client)

    # Decide to create ledger entry
    decide_body = {
        "decision_type": "approve",
        "approver_email": "approver@test.com",
        "decided_via": "web_ui",
    }
    await client.post(f"/approvals/{approval_id}/decide", json=decide_body)

    # Query ledger
    resp = await client.get("/ledger", params={"thread_id": "thread-123"}, headers=API_KEY_HEADER)
    assert resp.status_code == 200
    entries = resp.json()["entries"]
    assert len(entries) == 1
    assert entries[0]["content"]["thread_id"] == "thread-123"
    assert entries[0]["content"]["approval"]["decision_type"] == "approve"


@pytest.mark.asyncio
async def test_ledger_content_hash_deterministic(client: AsyncClient) -> None:
    """Verify content_hash is deterministic for the same input."""
    approval_id = await _create_interrupt(client)

    decide_body = {
        "decision_type": "approve",
        "decision_payload": {"amount": 750.0},
        "approver_email": "approver@test.com",
        "decided_via": "web_ui",
    }
    await client.post(f"/approvals/{approval_id}/decide", json=decide_body)

    resp = await client.get("/ledger", params={"thread_id": "thread-123"}, headers=API_KEY_HEADER)
    entries = resp.json()["entries"]
    assert len(entries) == 1
    entry = entries[0]

    # Verify content_hash starts with sha256:
    assert entry["content_hash"].startswith("sha256:")

    # Recompute hash from content (excluding hash and signature)
    from deliberate_server.auth import compute_content_hash

    content = dict(entry["content"])
    content_without_sig = {
        k: v for k, v in content.items() if k not in ("content_hash", "signature")
    }
    recomputed = compute_content_hash(content_without_sig)
    assert recomputed == entry["content_hash"]


# --- Full flow ---


@pytest.mark.asyncio
async def test_full_flow(client: AsyncClient) -> None:
    """Full flow: submit → status(pending) → decide → status(decided) → resume-ack → ledger."""
    # 1. Submit interrupt
    resp = await client.post("/interrupts", json=VALID_PAYLOAD, headers=API_KEY_HEADER)
    assert resp.status_code == 200
    approval_id = resp.json()["approval_id"]

    # 2. Check status — pending
    resp = await client.get(f"/approvals/{approval_id}/status", headers=API_KEY_HEADER)
    assert resp.json()["status"] == "pending"

    # 3. Get payload
    resp = await client.get(f"/approvals/{approval_id}/payload", headers=API_KEY_HEADER)
    assert resp.status_code == 200
    assert resp.json()["layout"] == "financial_decision"

    # 4. Decide
    decide_body = {
        "decision_type": "approve",
        "decision_payload": {"amount": 750.0},
        "rationale_category": "product_issue",
        "rationale_notes": "Confirmed bug",
        "approver_email": "approver@test.com",
        "review_duration_ms": 3000,
        "decided_via": "web_ui",
    }
    resp = await client.post(f"/approvals/{approval_id}/decide", json=decide_body)
    assert resp.status_code == 200

    # 5. Check status — decided
    resp = await client.get(f"/approvals/{approval_id}/status", headers=API_KEY_HEADER)
    data = resp.json()
    assert data["status"] == "decided"
    assert data["decision_type"] == "approve"

    # 6. Resume ACK
    resp = await client.post(
        f"/approvals/{approval_id}/resume-ack",
        json={"resume_status": "success", "resume_latency_ms": 200},
    )
    assert resp.status_code == 200

    # 7. Query ledger
    resp = await client.get("/ledger", params={"thread_id": "thread-123"}, headers=API_KEY_HEADER)
    entries = resp.json()["entries"]
    assert len(entries) == 1
    entry = entries[0]
    assert entry["resume_status"] == "success"
    assert entry["resume_latency_ms"] == 200
    assert entry["content"]["approval"]["decision_type"] == "approve"
