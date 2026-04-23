"""Tests for Policy CRUD API endpoints."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

REFUND_POLICY = {
    "name": "refund_approval",
    "matches": {"layout": "financial_decision"},
    "rules": [
        {
            "name": "auto_small",
            "when": "amount.value < 100",
            "action": "auto_approve",
            "rationale": "Small refund auto-approved",
        },
        {
            "name": "standard",
            "when": "amount.value >= 100",
            "action": "request_human",
            "approvers": {"any_of": ["finance_lead"]},
            "timeout": "4h",
            "notify": ["email"],
        },
    ],
}


@pytest.mark.asyncio
async def test_create_policy(client: AsyncClient, admin_api_key: str) -> None:
    """POST /policies returns 201 with name, version=1, rules."""
    resp = await client.post(
        "/policies",
        json=REFUND_POLICY,
        headers={"X-Deliberate-Api-Key": admin_api_key},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["name"] == "refund_approval"
    assert data["version"] == 1
    assert len(data["rules"]) == 2
    assert data["content_hash"].startswith("sha256:")


@pytest.mark.asyncio
async def test_create_duplicate_policy_returns_409(client: AsyncClient, admin_api_key: str) -> None:
    """Creating the same policy name twice returns 409."""
    headers = {"X-Deliberate-Api-Key": admin_api_key}
    resp1 = await client.post("/policies", json=REFUND_POLICY, headers=headers)
    assert resp1.status_code == 201

    resp2 = await client.post("/policies", json=REFUND_POLICY, headers=headers)
    assert resp2.status_code == 409


@pytest.mark.asyncio
async def test_list_policies(client: AsyncClient, admin_api_key: str) -> None:
    """GET /policies returns list with rule_count."""
    headers = {"X-Deliberate-Api-Key": admin_api_key}
    create_resp = await client.post("/policies", json=REFUND_POLICY, headers=headers)
    assert create_resp.status_code == 201

    resp = await client.get("/policies", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    policy = next(p for p in data if p["name"] == "refund_approval")
    assert policy["rule_count"] == 2
    assert policy["version"] == 1
    assert policy["content_hash"].startswith("sha256:")


@pytest.mark.asyncio
async def test_get_policy(client: AsyncClient, admin_api_key: str) -> None:
    """GET /policies/{name} returns full definition."""
    headers = {"X-Deliberate-Api-Key": admin_api_key}
    await client.post("/policies", json=REFUND_POLICY, headers=headers)

    resp = await client.get("/policies/refund_approval", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "refund_approval"
    assert data["version"] == 1
    assert "definition" in data
    assert "content_hash" in data
    assert "created_by" in data
    assert "created_at" in data
    assert "updated_at" in data


@pytest.mark.asyncio
async def test_get_nonexistent_policy_returns_404(client: AsyncClient, admin_api_key: str) -> None:
    """GET /policies/{name} returns 404 for unknown policy."""
    resp = await client.get(
        "/policies/does_not_exist",
        headers={"X-Deliberate-Api-Key": admin_api_key},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_update_policy_increments_version(client: AsyncClient, admin_api_key: str) -> None:
    """PUT /policies/{name} increments version to 2."""
    headers = {"X-Deliberate-Api-Key": admin_api_key}
    await client.post("/policies", json=REFUND_POLICY, headers=headers)

    updated = {
        "matches": {"layout": "financial_decision"},
        "rules": [
            {
                "name": "auto_small",
                "when": "amount.value < 50",
                "action": "auto_approve",
                "rationale": "Very small refund auto-approved",
            },
        ],
        "change_reason": "Lower threshold",
    }
    resp = await client.put("/policies/refund_approval", json=updated, headers=headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["version"] == 2
    assert data["name"] == "refund_approval"
    assert data["content_hash"].startswith("sha256:")


@pytest.mark.asyncio
async def test_delete_policy(client: AsyncClient, admin_api_key: str) -> None:
    """DELETE /policies/{name} returns 204, then GET returns 404."""
    headers = {"X-Deliberate-Api-Key": admin_api_key}
    await client.post("/policies", json=REFUND_POLICY, headers=headers)

    del_resp = await client.delete("/policies/refund_approval", headers=headers)
    assert del_resp.status_code == 204

    get_resp = await client.get("/policies/refund_approval", headers=headers)
    assert get_resp.status_code == 404


@pytest.mark.asyncio
async def test_policy_test_endpoint(client: AsyncClient, admin_api_key: str) -> None:
    """POST /policies/{name}/test dry-runs and matches auto_approve for small amount."""
    headers = {"X-Deliberate-Api-Key": admin_api_key}
    await client.post("/policies", json=REFUND_POLICY, headers=headers)

    test_payload = {
        "payload": {
            "layout": "financial_decision",
            "amount": {"value": 50, "currency": "USD"},
            "subject": "Test refund",
        }
    }
    resp = await client.post("/policies/refund_approval/test", json=test_payload, headers=headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["matched"] is True
    assert data["matched_rule"] == "auto_small"
    assert data["action"] == "auto_approve"


@pytest.mark.asyncio
async def test_policy_versions(client: AsyncClient, admin_api_key: str) -> None:
    """After create + update, GET /policies/{name}/versions returns 1 version entry."""
    headers = {"X-Deliberate-Api-Key": admin_api_key}
    await client.post("/policies", json=REFUND_POLICY, headers=headers)

    updated = {
        "matches": {"layout": "financial_decision"},
        "rules": [
            {
                "name": "auto_small",
                "when": "amount.value < 75",
                "action": "auto_approve",
                "rationale": "Adjusted threshold",
            },
        ],
        "change_reason": "Threshold adjustment",
    }
    await client.put("/policies/refund_approval", json=updated, headers=headers)

    resp = await client.get("/policies/refund_approval/versions", headers=headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert isinstance(data, list)
    # After 1 update, the old version (v1) is saved to history
    assert len(data) == 1
    assert data[0]["version"] == 1
    assert data[0]["content_hash"].startswith("sha256:")
    assert data[0]["changed_by"] == "test-admin"
    assert data[0]["change_reason"] == "Threshold adjustment"
