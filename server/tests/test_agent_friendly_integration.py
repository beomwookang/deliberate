"""Integration test: full agent-friendly workflow."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.anyio


async def test_full_agent_friendly_flow(client: AsyncClient, admin_api_key: str) -> None:
    """End-to-end flow: approvers → group → policy → agent key → verify scope isolation."""
    h = {"X-Deliberate-API-Key": admin_api_key}

    # 1. Create approvers
    resp = await client.post(
        "/approvers",
        headers=h,
        json={
            "id": "reviewer1",
            "email": "reviewer1@example.com",
            "display_name": "Reviewer One",
        },
    )
    assert resp.status_code == 201, resp.text

    resp = await client.post(
        "/approvers",
        headers=h,
        json={
            "id": "reviewer2",
            "email": "reviewer2@example.com",
        },
    )
    assert resp.status_code == 201, resp.text

    # 2. Create group
    resp = await client.post(
        "/groups",
        headers=h,
        json={
            "id": "review_team",
            "members": ["reviewer1", "reviewer2"],
        },
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["members"] == ["reviewer1", "reviewer2"]

    # 3. Create policy
    resp = await client.post(
        "/policies",
        headers=h,
        json={
            "name": "integration_test_policy",
            "matches": {"layout": "financial_decision"},
            "rules": [
                {
                    "name": "auto_tiny",
                    "when": "amount.value < 10",
                    "action": "auto_approve",
                    "rationale": "Tiny amount auto-approved",
                },
                {
                    "name": "need_review",
                    "when": "amount.value >= 10",
                    "action": "request_human",
                    "approvers": {"any_of": ["review_team"]},
                    "timeout": "1h",
                },
            ],
        },
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["version"] == 1

    # 4. Test policy (dry run) — small amount should auto-approve
    resp = await client.post(
        "/policies/integration_test_policy/test",
        headers=h,
        json={
            "payload": {
                "layout": "financial_decision",
                "subject": "Test Refund",
                "amount": {"value": 5, "currency": "USD"},
            },
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["action"] == "auto_approve"
    assert data["matched_rule"] == "auto_tiny"

    # 5. Test policy — larger amount should need review
    resp = await client.post(
        "/policies/integration_test_policy/test",
        headers=h,
        json={
            "payload": {
                "layout": "financial_decision",
                "subject": "Test Refund",
                "amount": {"value": 500, "currency": "USD"},
            },
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["action"] == "request_human"

    # 6. Create a scoped agent key
    resp = await client.post(
        "/api-keys",
        headers=h,
        json={
            "name": "test-scoped-agent",
            "role": "agent",
        },
    )
    assert resp.status_code == 201, resp.text
    agent_key = resp.json()["raw_key"]
    assert agent_key.startswith("dlb_ak_")

    # 7. Verify agent key CANNOT modify policies (scope isolation)
    resp = await client.post(
        "/policies",
        headers={"X-Deliberate-API-Key": agent_key},
        json={"name": "evil_policy", "matches": {}, "rules": []},
    )
    assert resp.status_code == 403, f"Expected 403, got {resp.status_code}: {resp.text}"

    # 8. Verify agent key CANNOT create approvers
    resp = await client.post(
        "/approvers",
        headers={"X-Deliberate-API-Key": agent_key},
        json={"id": "evil_approver", "email": "evil@example.com"},
    )
    assert resp.status_code == 403, f"Expected 403, got {resp.status_code}: {resp.text}"

    # 9. List policies (admin can read)
    resp = await client.get("/policies", headers=h)
    assert resp.status_code == 200, resp.text
    policies = resp.json()
    assert any(p["name"] == "integration_test_policy" for p in policies)

    # 10. List pending approvals (should be empty)
    resp = await client.get("/approvals", headers=h, params={"status": "pending"})
    assert resp.status_code == 200, resp.text

    # 11. Update policy (version increments)
    resp = await client.put(
        "/policies/integration_test_policy",
        headers=h,
        json={
            "matches": {"layout": "financial_decision"},
            "rules": [
                {
                    "name": "auto_tiny",
                    "when": "amount.value < 20",
                    "action": "auto_approve",
                    "rationale": "Bumped threshold",
                },
            ],
            "change_reason": "Raised auto-approve threshold",
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["version"] == 2

    # 12. Check version history — endpoint returns archived (old) versions only.
    # After one update (v1 → v2), history has exactly one entry: v1.
    resp = await client.get("/policies/integration_test_policy/versions", headers=h)
    assert resp.status_code == 200, resp.text
    versions = resp.json()
    assert len(versions) == 1
    assert versions[0]["version"] == 1

    # 13. Delete policy
    resp = await client.delete("/policies/integration_test_policy", headers=h)
    assert resp.status_code == 204

    # 14. Verify deleted policy returns 404
    resp = await client.get("/policies/integration_test_policy", headers=h)
    assert resp.status_code == 404
