"""Tests for approver and group CRUD endpoints."""

from __future__ import annotations

import pytest
from httpx import AsyncClient  # noqa: F401

# ---------------------------------------------------------------------------
# Approver tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_approver(client: AsyncClient, admin_api_key: str) -> None:
    resp = await client.post(
        "/approvers",
        json={"id": "alice", "email": "alice@example.com", "display_name": "Alice"},
        headers={"X-Deliberate-API-Key": admin_api_key},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["id"] == "alice"
    assert data["email"] == "alice@example.com"
    assert data["display_name"] == "Alice"
    assert data["ooo_active"] is False


@pytest.mark.asyncio
async def test_create_duplicate_approver_returns_409(
    client: AsyncClient, admin_api_key: str
) -> None:
    payload = {"id": "bob", "email": "bob@example.com"}
    headers = {"X-Deliberate-API-Key": admin_api_key}
    resp = await client.post("/approvers", json=payload, headers=headers)
    assert resp.status_code == 201
    resp2 = await client.post("/approvers", json=payload, headers=headers)
    assert resp2.status_code == 409


@pytest.mark.asyncio
async def test_list_approvers(client: AsyncClient, admin_api_key: str) -> None:
    headers = {"X-Deliberate-API-Key": admin_api_key}
    await client.post(
        "/approvers",
        json={"id": "carol", "email": "carol@example.com"},
        headers=headers,
    )
    resp = await client.get("/approvers", headers=headers)
    assert resp.status_code == 200
    ids = [a["id"] for a in resp.json()]
    assert "carol" in ids


@pytest.mark.asyncio
async def test_get_approver(client: AsyncClient, admin_api_key: str) -> None:
    headers = {"X-Deliberate-API-Key": admin_api_key}
    await client.post(
        "/approvers",
        json={"id": "dave", "email": "dave@example.com", "display_name": "Dave"},
        headers=headers,
    )
    resp = await client.get("/approvers/dave", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "dave"
    assert data["ooo_active"] is False
    assert "ooo_from" in data
    assert "ooo_until" in data
    assert "ooo_delegate_to" in data
    assert "updated_at" in data


@pytest.mark.asyncio
async def test_update_approver(client: AsyncClient, admin_api_key: str) -> None:
    headers = {"X-Deliberate-API-Key": admin_api_key}
    await client.post(
        "/approvers",
        json={"id": "eve", "email": "eve@example.com"},
        headers=headers,
    )
    resp = await client.put(
        "/approvers/eve",
        json={"email": "eve.new@example.com", "ooo_active": True},
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["email"] == "eve.new@example.com"
    assert data["ooo_active"] is True


@pytest.mark.asyncio
async def test_delete_approver(client: AsyncClient, admin_api_key: str) -> None:
    headers = {"X-Deliberate-API-Key": admin_api_key}
    await client.post(
        "/approvers",
        json={"id": "frank", "email": "frank@example.com"},
        headers=headers,
    )
    resp = await client.delete("/approvers/frank", headers=headers)
    assert resp.status_code == 204
    resp2 = await client.get("/approvers/frank", headers=headers)
    assert resp2.status_code == 404


# ---------------------------------------------------------------------------
# Group tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_group(client: AsyncClient, admin_api_key: str) -> None:
    headers = {"X-Deliberate-API-Key": admin_api_key}
    # Create members first
    await client.post(
        "/approvers", json={"id": "g1-alice", "email": "g1alice@example.com"}, headers=headers
    )
    await client.post(
        "/approvers", json={"id": "g1-bob", "email": "g1bob@example.com"}, headers=headers
    )
    resp = await client.post(
        "/groups",
        json={
            "id": "team-alpha",
            "members": ["g1-alice", "g1-bob"],
            "display_name": "Team Alpha",
        },
        headers=headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["id"] == "team-alpha"
    assert set(data["members"]) == {"g1-alice", "g1-bob"}
    assert data["display_name"] == "Team Alpha"


@pytest.mark.asyncio
async def test_create_group_with_invalid_member_returns_400(
    client: AsyncClient, admin_api_key: str
) -> None:
    headers = {"X-Deliberate-API-Key": admin_api_key}
    await client.post(
        "/approvers",
        json={"id": "g2-real", "email": "g2real@example.com"},
        headers=headers,
    )
    resp = await client.post(
        "/groups",
        json={"id": "team-beta", "members": ["g2-real", "nonexistent-user"]},
        headers=headers,
    )
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert "nonexistent-user" in detail


@pytest.mark.asyncio
async def test_list_groups(client: AsyncClient, admin_api_key: str) -> None:
    headers = {"X-Deliberate-API-Key": admin_api_key}
    await client.post(
        "/approvers", json={"id": "g3-member", "email": "g3m@example.com"}, headers=headers
    )
    await client.post(
        "/groups",
        json={"id": "team-gamma", "members": ["g3-member"]},
        headers=headers,
    )
    resp = await client.get("/groups", headers=headers)
    assert resp.status_code == 200
    ids = [g["id"] for g in resp.json()]
    assert "team-gamma" in ids


@pytest.mark.asyncio
async def test_update_group(client: AsyncClient, admin_api_key: str) -> None:
    headers = {"X-Deliberate-API-Key": admin_api_key}
    await client.post(
        "/approvers", json={"id": "g4-a", "email": "g4a@example.com"}, headers=headers
    )
    await client.post(
        "/approvers", json={"id": "g4-b", "email": "g4b@example.com"}, headers=headers
    )
    await client.post(
        "/groups",
        json={"id": "team-delta", "members": ["g4-a"]},
        headers=headers,
    )
    resp = await client.put(
        "/groups/team-delta",
        json={"members": ["g4-a", "g4-b"], "display_name": "Team Delta Updated"},
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert set(data["members"]) == {"g4-a", "g4-b"}
    assert data["display_name"] == "Team Delta Updated"


@pytest.mark.asyncio
async def test_delete_group(client: AsyncClient, admin_api_key: str) -> None:
    headers = {"X-Deliberate-API-Key": admin_api_key}
    await client.post(
        "/approvers", json={"id": "g5-member", "email": "g5m@example.com"}, headers=headers
    )
    await client.post(
        "/groups",
        json={"id": "team-epsilon", "members": ["g5-member"]},
        headers=headers,
    )
    resp = await client.delete("/groups/team-epsilon", headers=headers)
    assert resp.status_code == 204
    # Confirm it no longer appears in the list
    list_resp = await client.get("/groups", headers=headers)
    ids = [g["id"] for g in list_resp.json()]
    assert "team-epsilon" not in ids
