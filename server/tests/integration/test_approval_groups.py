"""Integration tests for approval groups (Fix 3: all_of multi-approver).

Tests the end-to-end flow for any_of and all_of approval modes.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime

os.environ.setdefault("SECRET_KEY", "group-test-secret-key-32chars!!")
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

from deliberate_server.auth import hash_api_key
from deliberate_server.config import settings
from deliberate_server.db.models import Base

_TEST_DB_URL = settings.database_url
API_KEY = "group-test-api-key"
API_KEY_HEADER = {"X-Deliberate-API-Key": API_KEY}


def _make_interrupt(thread_id: str = "group-thread", subject: str = "Test") -> dict:
    return {
        "thread_id": thread_id,
        "trace_id": f"trace-{thread_id}",
        "payload": {
            "layout": "financial_decision",
            "subject": subject,
            "amount": {"value": 750.0, "currency": "USD"},
            "customer": {"id": "cust_001", "display_name": "Test User"},
            "agent_reasoning": "Test reasoning",
            "evidence": [{"type": "ticket", "id": "#1", "summary": "Test"}],
        },
    }


def _decide_body(
    decision_type: str = "approve",
    email: str = "approver@test.com",
    notes: str | None = None,
    payload: dict | None = None,
) -> dict:
    return {
        "decision_type": decision_type,
        "decision_payload": payload,
        "rationale_category": "product_issue",
        "rationale_notes": notes or f"Testing {decision_type}",
        "approver_email": email,
        "review_duration_ms": 1000,
        "decided_via": "web_ui",
    }


@pytest_asyncio.fixture
async def client():
    engine = create_async_engine(_TEST_DB_URL, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with engine.begin() as conn:
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


# ============================================================
# Test: Response shape includes group fields
# ============================================================


@pytest.mark.asyncio
async def test_interrupt_response_has_group_fields(client: AsyncClient) -> None:
    resp = await client.post("/interrupts", json=_make_interrupt(), headers=API_KEY_HEADER)
    assert resp.status_code == 200
    data = resp.json()
    assert "approval_group_id" in data
    assert "approval_ids" in data
    assert "approval_mode" in data
    assert "approval_id" in data  # backward compat
    assert data["status"] == "pending"


# ============================================================
# Test: any_of — first approve → decided, others superseded
# ============================================================


@pytest.mark.asyncio
async def test_any_of_first_approve_decides_group(client: AsyncClient) -> None:
    """In any_of mode, the first decision wins."""
    resp = await client.post("/interrupts", json=_make_interrupt(), headers=API_KEY_HEADER)
    data = resp.json()
    group_id = data["approval_group_id"]
    approval_id = data["approval_ids"][0]

    # Group is pending
    resp = await client.get(f"/approval-groups/{group_id}/status")
    assert resp.json()["status"] == "pending"

    # Approve
    resp = await client.post(
        f"/approvals/{approval_id}/decide",
        json=_decide_body("approve", notes="Looks good"),
    )
    assert resp.status_code == 200

    # Group is now decided
    resp = await client.get(f"/approval-groups/{group_id}/status")
    group_data = resp.json()
    assert group_data["status"] == "decided"
    assert group_data["decision_type"] == "approve"


# ============================================================
# Test: all_of — one approves, still pending
# ============================================================


@pytest.mark.asyncio
async def test_all_of_one_approve_still_pending(client: AsyncClient) -> None:
    """In all_of, group stays pending until ALL approvers decide.

    We test this by directly creating a 2-approval group via the API.
    Since the M1 fallback creates any_of, we need a policy for all_of.
    For now, we test the group endpoint logic directly.
    """
    # Create two approvals in the same group manually
    from deliberate_server.db.models import Approval, Interrupt
    from deliberate_server.db.session import async_session

    interrupt_id = uuid.uuid4()
    group_id = uuid.uuid4()
    approval_1 = uuid.uuid4()
    approval_2 = uuid.uuid4()

    async with async_session() as session, session.begin():
        session.add(
            Interrupt(
                id=interrupt_id,
                application_id="default",
                thread_id="all-of-test",
                layout="financial_decision",
                payload={"layout": "financial_decision", "subject": "Test"},
            )
        )
        await session.flush()
        for aid, approver in [(approval_1, "alice"), (approval_2, "bob")]:
            session.add(
                Approval(
                    id=aid,
                    interrupt_id=interrupt_id,
                    approver_id=approver,
                    status="pending",
                    timeout_at=datetime(2026, 12, 31, tzinfo=UTC),
                    approval_group_id=group_id,
                    approval_mode="all_of",
                )
            )

    # Only alice decides
    resp = await client.post(
        f"/approvals/{approval_1}/decide",
        json=_decide_body("approve", email="alice@test.com", notes="Alice approves"),
    )
    assert resp.status_code == 200

    # Group still pending (bob hasn't decided)
    resp = await client.get(f"/approval-groups/{group_id}/status")
    assert resp.json()["status"] == "pending"


# ============================================================
# Test: all_of — both approve → decided with merged notes
# ============================================================


@pytest.mark.asyncio
async def test_all_of_both_approve_decided(client: AsyncClient) -> None:
    from deliberate_server.db.models import Approval, Interrupt
    from deliberate_server.db.session import async_session

    interrupt_id = uuid.uuid4()
    group_id = uuid.uuid4()
    approval_1 = uuid.uuid4()
    approval_2 = uuid.uuid4()

    async with async_session() as session, session.begin():
        session.add(
            Interrupt(
                id=interrupt_id,
                application_id="default",
                thread_id="all-of-both",
                layout="financial_decision",
                payload={"layout": "financial_decision", "subject": "Test"},
            )
        )
        await session.flush()
        for aid, approver in [(approval_1, "alice"), (approval_2, "bob")]:
            session.add(
                Approval(
                    id=aid,
                    interrupt_id=interrupt_id,
                    approver_id=approver,
                    status="pending",
                    timeout_at=datetime(2026, 12, 31, tzinfo=UTC),
                    approval_group_id=group_id,
                    approval_mode="all_of",
                )
            )

    # Alice approves
    resp = await client.post(
        f"/approvals/{approval_1}/decide",
        json=_decide_body("approve", email="alice@test.com", notes="Alice says yes"),
    )
    assert resp.status_code == 200

    # Bob approves
    resp = await client.post(
        f"/approvals/{approval_2}/decide",
        json=_decide_body("approve", email="bob@test.com", notes="Bob agrees"),
    )
    assert resp.status_code == 200

    # Group decided
    resp = await client.get(f"/approval-groups/{group_id}/status")
    data = resp.json()
    assert data["status"] == "decided"
    assert data["decision_type"] == "approve"
    # Notes merged from both
    assert "Alice says yes" in data["rationale_notes"]
    assert "Bob agrees" in data["rationale_notes"]


# ============================================================
# Test: all_of — one rejects → group decided as reject
# ============================================================


@pytest.mark.asyncio
async def test_all_of_one_reject_decides_group(client: AsyncClient) -> None:
    from deliberate_server.db.models import Approval, Interrupt
    from deliberate_server.db.session import async_session

    interrupt_id = uuid.uuid4()
    group_id = uuid.uuid4()
    approval_1 = uuid.uuid4()
    approval_2 = uuid.uuid4()

    async with async_session() as session, session.begin():
        session.add(
            Interrupt(
                id=interrupt_id,
                application_id="default",
                thread_id="all-of-reject",
                layout="financial_decision",
                payload={"layout": "financial_decision", "subject": "Test"},
            )
        )
        await session.flush()
        for aid, approver in [(approval_1, "alice"), (approval_2, "bob")]:
            session.add(
                Approval(
                    id=aid,
                    interrupt_id=interrupt_id,
                    approver_id=approver,
                    status="pending",
                    timeout_at=datetime(2026, 12, 31, tzinfo=UTC),
                    approval_group_id=group_id,
                    approval_mode="all_of",
                )
            )

    # Alice approves
    resp = await client.post(
        f"/approvals/{approval_1}/decide",
        json=_decide_body("approve", email="alice@test.com"),
    )
    assert resp.status_code == 200

    # Bob rejects
    resp = await client.post(
        f"/approvals/{approval_2}/decide",
        json=_decide_body("reject", email="bob@test.com", notes="Not justified"),
    )
    assert resp.status_code == 200

    # Group decided as reject (early reject)
    resp = await client.get(f"/approval-groups/{group_id}/status")
    data = resp.json()
    assert data["status"] == "decided"
    assert data["decision_type"] == "reject"
    assert "Not justified" in (data["rationale_notes"] or "")


# ============================================================
# Test: Ledger entries have approval_group field
# ============================================================


@pytest.mark.asyncio
async def test_ledger_has_approval_group(client: AsyncClient) -> None:
    resp = await client.post(
        "/interrupts", json=_make_interrupt(thread_id="ledger-group"), headers=API_KEY_HEADER
    )
    data = resp.json()
    approval_id = data["approval_id"]

    # Decide
    resp = await client.post(f"/approvals/{approval_id}/decide", json=_decide_body("approve"))
    assert resp.status_code == 200

    # Check ledger
    resp = await client.get("/ledger", params={"thread_id": "ledger-group"})
    entries = resp.json()["entries"]
    assert len(entries) >= 1
    content = entries[0]["content"]
    assert "approval_group" in content
    assert content["approval_group"]["group_id"] is not None
