# Agent-Friendly Deliberate — Design Spec

**Date:** 2026-04-23
**Status:** Approved
**Author:** Beomwoo Kang + Claude

## Summary

Transform Deliberate from a YAML-configured, code-only HITL approval layer into an API-driven, AI-agent-friendly platform. AI coding assistants (Claude Code, Cursor) and DevOps tools (CI/CD, Terraform) can programmatically manage policies, approvers, and API keys via REST API and MCP server.

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Primary users of MCP | Coding assistants (A) + DevOps tools (C) | Covers both dev-time and ops-time configuration |
| RBAC model | Resource-scoped permissions (C) | Flexible, prevents agents from modifying their own approval rules |
| Source of truth | Database (A) | YAML used only for initial seeding; clean separation |
| MCP deployment | Standalone Python package (B) | `uvx deliberate-mcp`; no npm dependency; thin REST wrapper |
| Agent docs | OpenAPI + llms.txt + MCP tool descriptions (C) | MCP users get docs via tool descriptions; non-MCP users get llms.txt |
| Approach | API-First (A) | REST API first, MCP as thin wrapper on top |

## Non-Goals

- Production AI agents (LangGraph graphs) do NOT get policy/approver management access. They only submit interrupts.
- LangGraph native `interrupt()` / `Command(resume=...)` integration is out of scope (future milestone).
- Multi-tenancy (`application_id` partitioning) is not expanded in this milestone.
- OAuth / SSO for API access — API key + scope is sufficient for now.

---

## Section 1: RBAC and API Key Model

### New Table: `api_keys`

```sql
CREATE TABLE api_keys (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    application_id  TEXT NOT NULL REFERENCES applications(id),
    name            TEXT NOT NULL,           -- "refund-agent-prod", "admin-cli"
    key_prefix      TEXT NOT NULL,           -- first 8 chars for identification
    key_hash        TEXT NOT NULL,           -- SHA-256 of full key
    scopes          TEXT[] NOT NULL,         -- ["interrupts:write", "policies:read"]
    created_by      TEXT NOT NULL,           -- creator email or "yaml-seed"
    expires_at      TIMESTAMPTZ,            -- null = no expiry
    revoked_at      TIMESTAMPTZ,            -- null = active
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_used_at    TIMESTAMPTZ
);
CREATE UNIQUE INDEX ix_api_keys_hash ON api_keys(key_hash);
CREATE INDEX ix_api_keys_app ON api_keys(application_id);
```

### Scope Definitions

| Scope | Description |
|-------|-------------|
| `interrupts:write` | Submit interrupts from SDK |
| `approvals:read` | Query approval status |
| `approvals:write` | Submit decisions (usually from UI) |
| `policies:read` | List/get policies |
| `policies:write` | Create/update/delete policies |
| `approvers:read` | List/get approvers and groups |
| `approvers:write` | Create/update/delete approvers and groups |
| `api_keys:read` | List API keys (prefix only, no secrets) |
| `api_keys:write` | Create/revoke API keys |
| `ledger:read` | Query audit log |
| `ledger:export` | Export ledger as CSV/JSON |

### Predefined Roles (convenience aliases)

| Role | Scopes |
|------|--------|
| `agent` | `interrupts:write`, `approvals:read` |
| `admin` | All scopes |
| `readonly` | `policies:read`, `approvers:read`, `ledger:read` |
| `operator` | `approvers:read`, `approvers:write`, `policies:read`, `api_keys:read` |

### Key Format

`dlb_ak_` + 32 bytes URL-safe base64 = `dlb_ak_A1b2C3d4E5f6...`

Prefix allows identifying which service the key belongs to. Raw key is returned exactly once on creation. Only the SHA-256 hash is stored.

### Authentication Flow

1. Request header: `X-Deliberate-API-Key: dlb_ak_xxxx...`
2. Server: SHA-256 hash → lookup in `api_keys` → check `revoked_at IS NULL` → check `expires_at`
3. Route-level: `require_scope("policies:write")` dependency injection
4. Migration: existing `applications.api_key_hash` → copied to `api_keys` with scope `["interrupts:write", "approvals:read"]`, name `"legacy-default"`
5. Bootstrap: `ADMIN_BOOTSTRAP_KEY` env var creates an admin-scoped key on first startup (if no admin key exists). Raw key logged once to stdout. This solves the chicken-and-egg problem of needing an admin key to create admin keys.

---

## Section 2: Policy & Approver CRUD API

### Policy Endpoints

| Method | Path | Scope | Description |
|--------|------|-------|-------------|
| `GET` | `/policies` | `policies:read` | List all policies (name, version, rule count, summary) |
| `GET` | `/policies/{name}` | `policies:read` | Get policy detail with full rules |
| `POST` | `/policies` | `policies:write` | Create policy |
| `PUT` | `/policies/{name}` | `policies:write` | Replace policy (creates new version) |
| `DELETE` | `/policies/{name}` | `policies:write` | Soft-delete policy |
| `POST` | `/policies/{name}/test` | `policies:read` | Dry-run: evaluate payload against policy without persisting |
| `GET` | `/policies/{name}/versions` | `policies:read` | List version history |

### New Table: `policies`

```sql
CREATE TABLE policies (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    application_id  TEXT NOT NULL REFERENCES applications(id),
    name            TEXT NOT NULL,
    version         INT NOT NULL DEFAULT 1,
    definition      JSONB NOT NULL,         -- full policy definition (same structure as YAML)
    content_hash    TEXT NOT NULL,           -- SHA-256 of definition
    created_by      TEXT NOT NULL,           -- API key name or "yaml-seed"
    is_active       BOOLEAN NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(application_id, name)
);
```

### New Table: `policy_versions`

```sql
CREATE TABLE policy_versions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    policy_id       UUID NOT NULL REFERENCES policies(id),
    version         INT NOT NULL,
    definition      JSONB NOT NULL,
    content_hash    TEXT NOT NULL,
    changed_by      TEXT NOT NULL,
    change_reason   TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_policy_versions_policy ON policy_versions(policy_id, version DESC);
```

**Version retention:** Maximum 50 versions per policy. On `PUT /policies/{name}`, if version count exceeds 50, the oldest version is deleted. This prevents unbounded growth of the `policy_versions` table.

### Approver Endpoints

| Method | Path | Scope | Description |
|--------|------|-------|-------------|
| `GET` | `/approvers` | `approvers:read` | List all approvers |
| `GET` | `/approvers/{id}` | `approvers:read` | Get approver detail |
| `POST` | `/approvers` | `approvers:write` | Create approver |
| `PUT` | `/approvers/{id}` | `approvers:write` | Update approver (email, OOO status, etc.) |
| `DELETE` | `/approvers/{id}` | `approvers:write` | Deactivate approver (soft delete) |
| `GET` | `/groups` | `approvers:read` | List groups |
| `POST` | `/groups` | `approvers:write` | Create group |
| `PUT` | `/groups/{id}` | `approvers:write` | Update group members |
| `DELETE` | `/groups/{id}` | `approvers:write` | Delete group (soft delete) |

### New Table: `approvers`

```sql
CREATE TABLE approvers (
    id              TEXT PRIMARY KEY,       -- human-readable: "finance_lead"
    application_id  TEXT NOT NULL REFERENCES applications(id),
    email           TEXT NOT NULL,
    display_name    TEXT,
    ooo_active      BOOLEAN NOT NULL DEFAULT false,
    ooo_from        TIMESTAMPTZ,
    ooo_until       TIMESTAMPTZ,
    ooo_delegate_to TEXT REFERENCES approvers(id),
    is_active       BOOLEAN NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_approvers_app ON approvers(application_id);
```

### New Table: `approver_groups`

```sql
CREATE TABLE approver_groups (
    id              TEXT PRIMARY KEY,       -- "finance_team"
    application_id  TEXT NOT NULL REFERENCES applications(id),
    display_name    TEXT,
    members         TEXT[] NOT NULL,        -- ["finance_lead", "cfo"]
    is_active       BOOLEAN NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_approver_groups_app ON approver_groups(application_id);
```

### API Key Endpoints

| Method | Path | Scope | Description |
|--------|------|-------|-------------|
| `GET` | `/api-keys` | `api_keys:read` | List keys (prefix only, no secrets) |
| `POST` | `/api-keys` | `api_keys:write` | Create key → raw key returned once |
| `DELETE` | `/api-keys/{id}` | `api_keys:write` | Revoke key |

### Additional Endpoint

| Method | Path | Scope | Description |
|--------|------|-------|-------------|
| `GET` | `/approvals?status=pending` | `approvals:read` | List pending approvals (new filter) |

### YAML Seeding Flow

```
Server startup
  → SEED_FROM_YAML=true (default) AND policies count = 0?
    → YES: Load config/policies/*.yaml + config/approvers.yaml → INSERT to DB
    → NO: Load from DB (YAML ignored)
```

### PolicyEngine Changes

- `load_policies()` → loads from DB (`SELECT * FROM policies WHERE is_active = true`)
- YAML loader extracted to `seed_policies(directory)` — runs only when DB is empty
- **Cache invalidation:** No background polling. API write endpoints (`POST`, `PUT`, `DELETE`) call `engine.invalidate_cache()` directly. The engine reloads from DB on next `evaluate()` call.
- `evaluate()` logic unchanged — input is the same dict structure whether from YAML or DB JSONB

### ApproverDirectory Changes

- `load()` → loads from DB
- YAML loader extracted to `seed_approvers(file_path)`
- Same cache invalidation pattern as PolicyEngine: write endpoints trigger reload
- `resolve()` logic unchanged

---

## Section 3: MCP Server (`deliberate-mcp`)

### Architecture

```
Claude Code / Cursor / other MCP clients
        |
        |  MCP Protocol (stdio)
        v
+-------------------------+
|   deliberate-mcp        |  <- standalone Python package (PyPI)
|   (FastMCP-based)       |
|                         |
|   httpx.AsyncClient ----+---> Deliberate Server REST API
|                         |     (http://localhost:4000)
+-------------------------+
```

- Built with **FastMCP** (Anthropic's official Python MCP SDK)
- **Zero business logic** — pure REST API wrapper
- Config via env vars: `DELIBERATE_URL`, `DELIBERATE_API_KEY`

### MCP Tools (17 total)

**Group 1: Policy Management** (coding assistants / DevOps)

| Tool Name | Description | REST Mapping |
|-----------|-------------|--------------|
| `list_policies` | List registered policies | `GET /policies` |
| `get_policy` | Get policy detail | `GET /policies/{name}` |
| `create_policy` | Create new policy with matches, rules, approvers | `POST /policies` |
| `update_policy` | Update existing policy | `PUT /policies/{name}` |
| `delete_policy` | Delete policy | `DELETE /policies/{name}` |
| `test_policy` | Dry-run: which rule matches a given payload? | `POST /policies/{name}/test` |

**Group 2: Approver Management**

| Tool Name | Description | REST Mapping |
|-----------|-------------|--------------|
| `list_approvers` | List all approvers | `GET /approvers` |
| `create_approver` | Add approver (id, email, display_name) | `POST /approvers` |
| `update_approver` | Update approver info (including OOO) | `PUT /approvers/{id}` |
| `list_groups` | List approver groups | `GET /groups` |
| `create_group` | Create group with members | `POST /groups` |
| `update_group` | Update group members | `PUT /groups/{id}` |

**Group 3: Operations (read-only)**

| Tool Name | Description | REST Mapping |
|-----------|-------------|--------------|
| `list_pending_approvals` | Currently pending approvals | `GET /approvals?status=pending` |
| `get_approval_status` | Check specific approval status | `GET /approvals/{id}/status` |
| `query_ledger` | Search audit log with filters | `GET /ledger` |
| `list_api_keys` | List API keys (prefix only) | `GET /api-keys` |
| `create_api_key` | Create new API key with scopes | `POST /api-keys` |

### MCP Tool Description Guidelines

Each tool description must:
1. **Start with a one-line summary** of what it does
2. **Explain WHEN to use it** (not just what it does)
3. **Include a concrete example** in the docstring
4. **Document all parameters** with types and constraints
5. **Describe the return value** structure

Tool descriptions ARE the docs for MCP users. Quality here directly impacts agent usability.

### Scope Enforcement

The API key passed to the MCP server determines which tools are usable. If a tool calls an endpoint the key doesn't have scope for, the server returns 403, and the MCP tool returns an error message explaining which scope is needed.

### Package Structure

```
mcp/
├── pyproject.toml              # name: deliberate-mcp
├── src/
│   └── deliberate_mcp/
│       ├── __init__.py
│       ├── __main__.py         # entry point for uvx deliberate-mcp
│       ├── server.py           # FastMCP server definition
│       ├── tools/
│       │   ├── policies.py     # Policy CRUD tools
│       │   ├── approvers.py    # Approver CRUD tools
│       │   └── operations.py   # Read-only operations tools
│       └── client.py           # httpx wrapper for REST API calls
└── tests/
```

### Claude Code Configuration Example

```json
{
  "mcpServers": {
    "deliberate": {
      "command": "uvx",
      "args": ["deliberate-mcp"],
      "env": {
        "DELIBERATE_URL": "http://localhost:4000",
        "DELIBERATE_API_KEY": "dlb_ak_..."
      }
    }
  }
}
```

---

## Section 4: Documentation

### New Files

| File | Content |
|------|---------|
| `llms.txt` | LLM-friendly project summary: what Deliberate is, core concepts, common tasks, API overview, auth model |
| `docs/admin-api.md` | Complete Admin REST API reference: all CRUD endpoints, request/response examples, scope requirements, error codes |
| `docs/mcp.md` | MCP server install/config guide: Claude Code setup, Cursor setup, tool-by-tool usage examples |
| `docs/rbac.md` | RBAC model: scope list, predefined roles, API key lifecycle (create/rotate/revoke) |
| `docs/migration-guide.md` | YAML-to-DB migration: what changes, what stays the same, step-by-step upgrade |

### Modified Files

| File | Changes |
|------|---------|
| `README.md` | Add "Agent-Friendly" section, MCP in installation, Admin API in architecture diagram |
| `docs/quickstart.md` | Add "Option B: Configure via API" alongside existing YAML instructions |
| `docs/security.md` | Add RBAC section, API key scope model, key rotation guidance |

### OpenAPI

FastAPI auto-generates `openapi.json`. All new endpoints include:
- Detailed docstrings with parameter descriptions
- Request/response examples via `model_config` JSON schema examples
- Tags: `policies`, `approvers`, `api-keys`, `interrupts`, `ledger`, `auth`
- Available at `/docs` (Swagger UI) and `/redoc` (ReDoc)

---

## Section 5: Database Migration and Code Changes

### Alembic Migration: `0006_agent_friendly`

**New tables (5):** `api_keys`, `policies`, `policy_versions`, `approvers`, `approver_groups`

**Data migration:**
- Copy existing `applications.api_key_hash` → `api_keys` row with scope `["interrupts:write", "approvals:read"]`, name `"legacy-default"`
- `applications.api_key_hash` column retained for backward compatibility (not removed)

### Code Change Map

| File | Change |
|------|--------|
| `server/src/deliberate_server/db/models.py` | Add 5 new SQLAlchemy models |
| `server/src/deliberate_server/api/auth.py` | Rewrite `api_key_auth()` to query `api_keys` table. Add `require_scope(scope)` dependency. |
| `server/src/deliberate_server/policy/engine.py` | `load_policies()` → DB query. Extract `seed_policies()`. Remove file-watching thread. Add `invalidate_cache()`. |
| `server/src/deliberate_server/policy/directory.py` | `load()` → DB query. Extract `seed_approvers()`. Remove file-watching thread. Add `invalidate_cache()`. |
| `server/src/deliberate_server/api/routes/policies.py` | **New.** 7 endpoints for policy CRUD + test + versions. |
| `server/src/deliberate_server/api/routes/approvers.py` | **New.** 9 endpoints for approver/group CRUD. |
| `server/src/deliberate_server/api/routes/api_keys.py` | **New.** 3 endpoints for key management. |
| `server/src/deliberate_server/api/routes/interrupts.py` | Add `require_scope("interrupts:write")` |
| `server/src/deliberate_server/api/routes/ledger.py` | Add `require_scope("ledger:read")` / `require_scope("ledger:export")` |
| `server/src/deliberate_server/api/routes/approvals.py` | Add `?status=pending` filter. Add `require_scope("approvals:read")`. |
| `server/src/deliberate_server/config.py` | Add `SEED_FROM_YAML: bool = True` |
| `server/src/deliberate_server/main.py` | Register new routers, call seeding on startup |

### Backward Compatibility

| Item | How it's preserved |
|------|-------------------|
| Existing API keys | Auto-migrated to `api_keys` table with agent scopes |
| Existing YAML workflow | `SEED_FROM_YAML=true` seeds DB on first start |
| Existing SDK code | `@approval_gate`, `DeliberateClient` unchanged |
| Existing auth header | `X-Deliberate-API-Key` format unchanged |
| Existing endpoints | All preserved, scope checks added (existing keys have required scopes) |

### New Package

```
mcp/
├── pyproject.toml      # deliberate-mcp, depends on httpx + mcp[fastmcp]
├── src/deliberate_mcp/
└── tests/
```

---

## Risk Notes

1. **policy_versions growth:** Capped at 50 versions per policy. Oldest auto-deleted on overflow.
2. **MCP tool count (17):** Manageable, but tool description quality is critical for agent usability. Each description must include when-to-use context and concrete examples.
3. **Cache invalidation:** API write endpoints trigger immediate cache invalidation. No background DB polling (eliminated as redundant).
4. **Seeding idempotency:** `seed_from_yaml_if_empty()` checks `count = 0` before inserting. Safe to restart multiple times.
