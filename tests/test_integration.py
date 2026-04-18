"""Integration test for the full Deliberate M1 flow.

Requires:
  - Postgres running (docker compose up -d postgres)
  - Server running (or use the test client approach)

This test exercises the full flow programmatically:
  1. Submit an interrupt (simulating the SDK)
  2. Check status (pending)
  3. Fetch payload (verify layout data)
  4. Submit a decision (simulating the UI)
  5. Check status (decided)
  6. Submit resume ACK (simulating the SDK)
  7. Query the ledger and verify the entry
"""

from __future__ import annotations

import os

os.environ.setdefault("SECRET_KEY", "integration-test-secret-key-32chars!")
os.environ.setdefault("DEFAULT_APPROVER_EMAIL", "approver@test.com")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://deliberate:deliberate@localhost:5432/deliberate",
)

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from deliberate_server.auth import compute_content_hash, hash_api_key
from deliberate_server.config import settings
from deliberate_server.db.models import Base

_TEST_DB_URL = settings.database_url
API_KEY = "integration-test-api-key"
API_KEY_HEADER = {"X-Deliberate-API-Key": API_KEY}


@pytest_asyncio.fixture
async def client() -> AsyncClient:
    """Full integration test client."""
    engine = create_async_engine(_TEST_DB_URL, poolclass=NullPool)

    # Ensure tables exist and seed data
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        for tbl in ("ledger_entries", "decisions", "approvals", "interrupts", "approvers"):
            await conn.execute(text(f"DELETE FROM {tbl}"))
        await conn.execute(text("DELETE FROM applications"))
        await conn.execute(
            text(
                "INSERT INTO applications (id, display_name, api_key_hash) "
                "VALUES (:id, :name, :hash)"
            ),
            {"id": "default", "name": "Test App", "hash": hash_api_key(API_KEY)},
        )

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    import deliberate_server.db.session as session_module

    original = session_module.async_session
    session_module.async_session = factory

    from deliberate_server.main import app

    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    session_module.async_session = original
    await engine.dispose()


@pytest.mark.asyncio
async def test_full_m1_flow(client: AsyncClient) -> None:
    """Complete M1 integration test: interrupt → decide → resume → ledger."""

    # 1. Submit interrupt
    interrupt_body = {
        "thread_id": "integration-thread-001",
        "trace_id": "integration-trace-001",
        "payload": {
            "layout": "financial_decision",
            "subject": "Refund for customer #4821",
            "amount": {"value": 750.0, "currency": "USD"},
            "customer": {
                "id": "cust_4821",
                "display_name": "Maya Chen",
                "tenure": "18 months",
            },
            "agent_reasoning": "Bug confirmed by engineering. No prior refunds.",
            "evidence": [
                {
                    "type": "ticket",
                    "id": "#4821",
                    "summary": "Bug confirmed",
                    "url": "https://support.example.com/4821",
                },
                {
                    "type": "history",
                    "summary": "No prior refunds",
                },
            ],
            "rationale_categories": [
                "product_issue",
                "retention",
                "policy_exception",
                "other",
            ],
        },
    }

    resp = await client.post("/interrupts", json=interrupt_body, headers=API_KEY_HEADER)
    assert resp.status_code == 200, f"Submit interrupt failed: {resp.text}"
    data = resp.json()
    approval_id = data["approval_id"]
    assert data["status"] == "pending"
    print(f"  [1] Interrupt submitted, approval_id={approval_id}")

    # 2. Check status — should be pending
    resp = await client.get(f"/approvals/{approval_id}/status")
    assert resp.status_code == 200
    assert resp.json()["status"] == "pending"
    print("  [2] Status: pending")

    # 3. Fetch payload — verify layout and data
    resp = await client.get(f"/approvals/{approval_id}/payload")
    assert resp.status_code == 200
    payload_data = resp.json()
    assert payload_data["layout"] == "financial_decision"
    assert payload_data["payload"]["subject"] == "Refund for customer #4821"
    assert payload_data["payload"]["amount"]["value"] == 750.0
    assert len(payload_data["payload"]["evidence"]) == 2
    print("  [3] Payload fetched: financial_decision layout, correct data")

    # 4. Submit decision — approve
    decide_body = {
        "decision_type": "approve",
        "decision_payload": {"amount": 750.0},
        "rationale_category": "product_issue",
        "rationale_notes": "Bug confirmed by engineering, one-time policy exception approved",
        "approver_email": "approver@test.com",
        "review_duration_ms": 5200,
        "decided_via": "web_ui",
    }
    resp = await client.post(f"/approvals/{approval_id}/decide", json=decide_body)
    assert resp.status_code == 200
    assert resp.json()["status"] == "decided"
    print("  [4] Decision submitted: approve")

    # 5. Check status — should be decided with decision details
    resp = await client.get(f"/approvals/{approval_id}/status")
    assert resp.status_code == 200
    status_data = resp.json()
    assert status_data["status"] == "decided"
    assert status_data["decision_type"] == "approve"
    assert status_data["decision_payload"] == {"amount": 750.0}
    assert status_data["rationale_category"] == "product_issue"
    print("  [5] Status: decided, decision_type=approve")

    # 6. Submit resume ACK
    ack_body = {"resume_status": "success", "resume_latency_ms": 342}
    resp = await client.post(f"/approvals/{approval_id}/resume-ack", json=ack_body)
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    print("  [6] Resume ACK sent: success, 342ms")

    # 7. Query the ledger by thread_id
    resp = await client.get("/ledger", params={"thread_id": "integration-thread-001"})
    assert resp.status_code == 200
    entries = resp.json()
    assert len(entries) == 1, f"Expected 1 ledger entry, got {len(entries)}"

    entry = entries[0]
    content = entry["content"]

    # Verify ledger content structure
    assert content["thread_id"] == "integration-thread-001"
    assert content["trace_id"] == "integration-trace-001"
    assert content["application_id"] == "default"
    assert content["interrupt"]["layout"] == "financial_decision"
    assert content["approval"]["decision_type"] == "approve"
    assert content["approval"]["approver_email"] == "approver@test.com"
    assert content["approval"]["rationale_category"] == "product_issue"
    assert content["approval"]["decided_via"] == "web_ui"
    assert content["approval"]["review_duration_ms"] == 5200

    # Verify resume was updated
    assert entry["resume_status"] == "success"
    assert entry["resume_latency_ms"] == 342

    # Verify content hash is valid
    assert entry["content_hash"].startswith("sha256:")
    excluded = ("content_hash", "signature")
    content_for_hash = {k: v for k, v in content.items() if k not in excluded}
    recomputed_hash = compute_content_hash(content_for_hash)
    assert recomputed_hash == entry["content_hash"], "Content hash mismatch after round-trip"

    print("  [7] Ledger entry verified: complete and hash-valid")

    # 8. Verify already-decided returns 409
    resp = await client.post(f"/approvals/{approval_id}/decide", json=decide_body)
    assert resp.status_code == 409
    print("  [8] Double-decide correctly returns 409")

    print("\n  ALL CHECKS PASSED")
