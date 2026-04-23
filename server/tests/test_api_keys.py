"""Tests for API key management endpoints."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_api_key(client: AsyncClient, admin_api_key: str) -> None:
    """Creating a key returns 201, raw_key starts with dlb_ak_, has key_prefix."""
    resp = await client.post(
        "/api-keys",
        json={"name": "my-new-key", "role": "agent"},
        headers={"x-deliberate-api-key": admin_api_key},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["raw_key"].startswith("dlb_ak_")
    assert data["key_prefix"] == data["raw_key"][:16]
    assert data["name"] == "my-new-key"
    assert "key_hash" not in data


@pytest.mark.asyncio
async def test_create_api_key_with_role(client: AsyncClient, admin_api_key: str) -> None:
    """role='agent' resolves to correct scopes."""
    resp = await client.post(
        "/api-keys",
        json={"name": "agent-key", "role": "agent"},
        headers={"x-deliberate-api-key": admin_api_key},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert sorted(data["scopes"]) == sorted(["interrupts:write", "approvals:read"])


@pytest.mark.asyncio
async def test_created_key_works(client: AsyncClient, admin_api_key: str) -> None:
    """A newly created key with api_keys:read scope can authenticate against GET /api-keys."""
    # Create a key with api_keys:read scope
    resp = await client.post(
        "/api-keys",
        json={"name": "reader-key", "scopes": ["api_keys:read"]},
        headers={"x-deliberate-api-key": admin_api_key},
    )
    assert resp.status_code == 201
    new_raw_key = resp.json()["raw_key"]

    # Use the new key to list api keys
    list_resp = await client.get(
        "/api-keys",
        headers={"x-deliberate-api-key": new_raw_key},
    )
    assert list_resp.status_code == 200


@pytest.mark.asyncio
async def test_list_api_keys(client: AsyncClient, admin_api_key: str) -> None:
    """List endpoint returns keys without raw_key or key_hash fields."""
    resp = await client.get(
        "/api-keys",
        headers={"x-deliberate-api-key": admin_api_key},
    )
    assert resp.status_code == 200
    keys = resp.json()
    assert isinstance(keys, list)
    assert len(keys) > 0
    for key in keys:
        assert "raw_key" not in key
        assert "key_hash" not in key
        assert "id" in key
        assert "name" in key
        assert "key_prefix" in key
        assert "scopes" in key


@pytest.mark.asyncio
async def test_revoke_api_key(client: AsyncClient, admin_api_key: str) -> None:
    """Create a key, revoke it, verify the revoked key returns 401."""
    # Create
    create_resp = await client.post(
        "/api-keys",
        json={"name": "to-revoke", "role": "agent"},
        headers={"x-deliberate-api-key": admin_api_key},
    )
    assert create_resp.status_code == 201
    data = create_resp.json()
    key_id = data["id"]
    raw_key = data["raw_key"]

    # Verify it works before revocation
    check_resp = await client.get(
        "/api-keys",
        headers={"x-deliberate-api-key": admin_api_key},
    )
    assert check_resp.status_code == 200

    # Revoke
    revoke_resp = await client.delete(
        f"/api-keys/{key_id}",
        headers={"x-deliberate-api-key": admin_api_key},
    )
    assert revoke_resp.status_code == 204

    # Attempt to use revoked key on an auth-gated endpoint
    auth_resp = await client.get(
        "/api-keys",
        headers={"x-deliberate-api-key": raw_key},
    )
    assert auth_resp.status_code == 401
