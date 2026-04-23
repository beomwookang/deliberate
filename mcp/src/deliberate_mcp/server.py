"""Deliberate MCP server — 17 tools for HITL approval management."""
from __future__ import annotations

import json
from typing import Any

from mcp.server.fastmcp import FastMCP

from deliberate_mcp.client import DeliberateAPIClient

mcp = FastMCP("Deliberate")
_client = DeliberateAPIClient()


def _dump(result: Any) -> str:
    return json.dumps(result, indent=2)


# ---------------------------------------------------------------------------
# Policy Management
# ---------------------------------------------------------------------------


@mcp.tool()
async def list_policies() -> str:
    """List all approval policies defined in the Deliberate server configuration."""
    result = await _client.get("/policies")
    return _dump(result)


@mcp.tool()
async def get_policy(name: str) -> str:
    """Retrieve a single policy by name, including its match conditions and approval rules."""
    result = await _client.get(f"/policies/{name}")
    return _dump(result)


@mcp.tool()
async def create_policy(name: str, matches: dict[str, Any], rules: list[Any]) -> str:
    """Create a new approval policy with match conditions and ordered approval rules."""
    result = await _client.post("/policies", json={"name": name, "matches": matches, "rules": rules})
    return _dump(result)


@mcp.tool()
async def update_policy(
    name: str,
    matches: dict[str, Any],
    rules: list[Any],
    change_reason: str | None = None,
) -> str:
    """Update an existing policy's match conditions, rules, and optional change reason for audit."""
    body: dict[str, Any] = {"matches": matches, "rules": rules}
    if change_reason is not None:
        body["change_reason"] = change_reason
    result = await _client.put(f"/policies/{name}", json=body)
    return _dump(result)


@mcp.tool()
async def delete_policy(name: str) -> str:
    """Delete a policy by name. Returns confirmation or error if the policy does not exist."""
    result = await _client.delete(f"/policies/{name}")
    return _dump(result)


@mcp.tool()
async def test_policy(name: str, payload: dict[str, Any]) -> str:
    """Dry-run a policy against a sample interrupt payload to preview which rules would match."""
    result = await _client.post(f"/policies/{name}/test", json={"payload": payload})
    return _dump(result)


# ---------------------------------------------------------------------------
# Approver Management
# ---------------------------------------------------------------------------


@mcp.tool()
async def list_approvers() -> str:
    """List all individual approvers registered in the Deliberate approver directory."""
    result = await _client.get("/approvers")
    return _dump(result)


@mcp.tool()
async def create_approver(
    id: str,
    email: str,
    display_name: str | None = None,
) -> str:
    """Create a new approver entry with an ID, email address, and optional display name."""
    body: dict[str, Any] = {"id": id, "email": email}
    if display_name is not None:
        body["display_name"] = display_name
    result = await _client.post("/approvers", json=body)
    return _dump(result)


@mcp.tool()
async def update_approver(
    id: str,
    email: str | None = None,
    display_name: str | None = None,
    ooo_active: bool | None = None,
) -> str:
    """Update an approver's email, display name, or out-of-office status by their ID."""
    body: dict[str, Any] = {}
    if email is not None:
        body["email"] = email
    if display_name is not None:
        body["display_name"] = display_name
    if ooo_active is not None:
        body["ooo_active"] = ooo_active
    result = await _client.put(f"/approvers/{id}", json=body)
    return _dump(result)


@mcp.tool()
async def list_groups() -> str:
    """List all approver groups, including their members, defined in the approver directory."""
    result = await _client.get("/groups")
    return _dump(result)


@mcp.tool()
async def create_group(
    id: str,
    members: list[str],
    display_name: str | None = None,
) -> str:
    """Create a new approver group with an ID, member list, and optional display name."""
    body: dict[str, Any] = {"id": id, "members": members}
    if display_name is not None:
        body["display_name"] = display_name
    result = await _client.post("/groups", json=body)
    return _dump(result)


@mcp.tool()
async def update_group(
    id: str,
    members: list[str] | None = None,
    display_name: str | None = None,
) -> str:
    """Update an approver group's member list or display name by its group ID."""
    body: dict[str, Any] = {}
    if members is not None:
        body["members"] = members
    if display_name is not None:
        body["display_name"] = display_name
    result = await _client.put(f"/groups/{id}", json=body)
    return _dump(result)


# ---------------------------------------------------------------------------
# Operations
# ---------------------------------------------------------------------------


@mcp.tool()
async def list_pending_approvals() -> str:
    """List all approvals currently awaiting a human decision (status=pending)."""
    result = await _client.get("/approvals", params={"status": "pending"})
    return _dump(result)


@mcp.tool()
async def get_approval_status(approval_id: str) -> str:
    """Get the current status and decision details for a specific approval by its ID."""
    result = await _client.get(f"/approvals/{approval_id}/status")
    return _dump(result)


@mcp.tool()
async def query_ledger(
    thread_id: str | None = None,
    approver_id: str | None = None,
    limit: int = 20,
) -> str:
    """Query the immutable audit ledger, optionally filtered by thread ID or approver ID."""
    params: dict[str, Any] = {"limit": limit}
    if thread_id is not None:
        params["thread_id"] = thread_id
    if approver_id is not None:
        params["approver_id"] = approver_id
    result = await _client.get("/ledger", params=params)
    return _dump(result)


@mcp.tool()
async def list_api_keys() -> str:
    """List all API keys registered with the Deliberate server, excluding secret values."""
    result = await _client.get("/api-keys")
    return _dump(result)


@mcp.tool()
async def create_api_key(
    name: str,
    role: str | None = None,
    scopes: list[str] | None = None,
) -> str:
    """Create a new API key with a name, optional role, and optional permission scopes."""
    body: dict[str, Any] = {"name": name}
    if role is not None:
        body["role"] = role
    if scopes is not None:
        body["scopes"] = scopes
    result = await _client.post("/api-keys", json=body)
    return _dump(result)


def main() -> None:
    mcp.run(transport="stdio")
