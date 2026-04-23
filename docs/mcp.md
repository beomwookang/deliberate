# Deliberate MCP Server

The Deliberate MCP server exposes the Deliberate Admin API as a set of tools that AI coding assistants (Claude Code, Cursor, Windsurf, etc.) can call directly. Instead of switching to a terminal to run `curl` commands, you can ask your assistant to create a policy, add an approver, or check pending approvals — all without leaving the editor.

The MCP server is a thin REST wrapper. It does not contain business logic; every tool call translates directly to an Admin API request.

---

## Installation

**Option A: pip**

```bash
pip install deliberate-mcp
```

**Option B: uvx (no install required)**

```bash
uvx deliberate-mcp
```

---

## Configuration

The MCP server reads two environment variables:

| Variable | Description |
|---|---|
| `DELIBERATE_URL` | Base URL of the Deliberate server. Default: `http://localhost:4000` |
| `DELIBERATE_API_KEY` | API key with the scopes needed for the tools you want to use. An `admin`-role key unlocks all tools. |

Set these in your shell or in the MCP configuration block (see below).

---

## Claude Code Setup

Add the following to `~/.claude/settings.json` (or your project-level `.claude/settings.json`):

```json
{
  "mcpServers": {
    "deliberate": {
      "command": "uvx",
      "args": ["deliberate-mcp"],
      "env": {
        "DELIBERATE_URL": "http://localhost:4000",
        "DELIBERATE_API_KEY": "dlb_ak_your-admin-key-here"
      }
    }
  }
}
```

If you installed via pip instead of uvx:

```json
{
  "mcpServers": {
    "deliberate": {
      "command": "deliberate-mcp",
      "env": {
        "DELIBERATE_URL": "http://localhost:4000",
        "DELIBERATE_API_KEY": "dlb_ak_your-admin-key-here"
      }
    }
  }
}
```

Restart Claude Code after saving the config. Verify the server is connected:

```
/mcp
```

You should see `deliberate` listed as a connected MCP server.

---

## Cursor Setup

Open Cursor Settings → MCP → Add Server:

```json
{
  "deliberate": {
    "command": "uvx",
    "args": ["deliberate-mcp"],
    "env": {
      "DELIBERATE_URL": "http://localhost:4000",
      "DELIBERATE_API_KEY": "dlb_ak_your-admin-key-here"
    }
  }
}
```

Or add directly to `~/.cursor/mcp.json`.

---

## Tool Overview

| Tool | Description |
|---|---|
| `list_policies` | List all policies in the database |
| `get_policy` | Get a policy by name including all rules |
| `create_policy` | Create a new policy with rules |
| `update_policy` | Replace an existing policy |
| `delete_policy` | Delete a policy by name |
| `test_policy` | Test a policy against a sample payload |
| `list_policy_versions` | List historical versions of a policy |
| `list_approvers` | List all approvers |
| `get_approver` | Get an approver by ID |
| `create_approver` | Create a new approver |
| `update_approver` | Update an approver (e.g., set out-of-office) |
| `delete_approver` | Delete an approver |
| `list_groups` | List all approver groups |
| `get_group` | Get a group with resolved member details |
| `create_group` | Create a new group |
| `delete_group` | Delete a group |
| `list_api_keys` | List API keys (metadata only; no raw key values) |
| `create_api_key` | Create a new scoped API key |
| `revoke_api_key` | Revoke an API key by ID |

---

## Example Workflows

### Set up approval routing for a new agent

Ask your assistant:

> "Create an approver named legal_lead with email legal@example.com, then create a policy called contract_review that auto-approves documents under 5 pages and routes everything else to legal_lead with a 24-hour timeout."

The assistant will call `create_approver` and then `create_policy` in sequence, using the correct request shapes.

### Check how a policy would route a specific request

Ask your assistant:

> "Test the refund_approval policy against a $3,500 refund request for customer C-042."

The assistant will call `test_policy` with the sample payload and report which rule matched, who would be notified, and what the timeout would be.

### Rotate an API key

Ask your assistant:

> "Create a new agent-role API key named refund-agent-prod-v2, then revoke the old key with ID 550e8400-..."

The assistant will call `create_api_key`, display the new key value (store it immediately), then call `revoke_api_key` on the old key.

### Review pending approvals for a thread

Ask your assistant:

> "Show me the ledger entries for thread ID 550e8400-e29b-41d4-a716-446655440000."

The assistant will call the ledger query tool and display the audit trail inline.

---

## Scope Requirements

The MCP server uses the same API key as direct REST calls. The key must have the scopes for the tools you want to use. An `admin`-role key (`api_keys:write` + all other scopes) unlocks every tool.

For read-only use in a coding assistant context, an `operator`-role key (`policies:read/write`, `approvers:read/write`, `groups:read/write`, `ledger:read`) is sufficient for most workflows without granting key management access.

See [RBAC and API Key Management](./rbac.md) for scope definitions.
