# Agent-Friendly Deliberate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform Deliberate into an API-driven, AI-agent-friendly platform with scoped RBAC, Policy/Approver/API Key CRUD APIs, standalone MCP server, and agent-facing documentation.

**Architecture:** REST API-First approach — add admin CRUD endpoints to the existing FastAPI server with scope-based RBAC, then wrap them in a standalone MCP server (`deliberate-mcp`) as a thin httpx client. DB becomes the source of truth for policies and approvers; YAML files are used only for initial seeding.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 (async), Alembic, FastMCP (Python MCP SDK), httpx, PostgreSQL

**Spec:** `docs/superpowers/specs/2026-04-23-agent-friendly-design.md`

---

## File Structure

### New Files
| File | Responsibility |
|------|---------------|
| `server/src/deliberate_server/api/deps.py` | Auth dependencies: `get_api_key()`, `require_scope()` |
| `server/src/deliberate_server/api/routes/policies.py` | Policy CRUD (7 endpoints) |
| `server/src/deliberate_server/api/routes/approvers_admin.py` | Approver + Group CRUD (9 endpoints) |
| `server/src/deliberate_server/api/routes/api_keys.py` | API Key management (3 endpoints) |
| `server/src/deliberate_server/seeding.py` | YAML → DB seed logic |
| `server/alembic/versions/0006_agent_friendly.py` | Migration for 4 new tables + data migration |
| `server/tests/test_rbac.py` | RBAC auth tests |
| `server/tests/test_policies_api.py` | Policy CRUD tests |
| `server/tests/test_approvers_api.py` | Approver/Group CRUD tests |
| `server/tests/test_api_keys.py` | API Key management tests |
| `server/tests/test_seeding.py` | YAML seeding tests |
| `mcp/pyproject.toml` | deliberate-mcp package definition |
| `mcp/src/deliberate_mcp/__init__.py` | Package init |
| `mcp/src/deliberate_mcp/__main__.py` | Entry point for `uvx deliberate-mcp` |
| `mcp/src/deliberate_mcp/server.py` | FastMCP server with all tool definitions |
| `mcp/src/deliberate_mcp/client.py` | httpx wrapper for REST API calls |
| `mcp/tests/test_tools.py` | MCP tool unit tests |
| `llms.txt` | LLM-friendly project summary |
| `docs/admin-api.md` | Admin REST API reference |
| `docs/mcp.md` | MCP server guide |
| `docs/rbac.md` | RBAC model documentation |
| `docs/migration-guide.md` | YAML→DB migration guide |

### Modified Files
| File | Change |
|------|--------|
| `server/src/deliberate_server/db/models.py` | Add `ApiKey`, `PolicyRecord`, `PolicyVersion`, `ApproverGroup` models |
| `server/src/deliberate_server/auth.py` | Add `generate_api_key()` function |
| `server/src/deliberate_server/config.py` | Add `seed_from_yaml`, `admin_bootstrap_key` settings |
| `server/src/deliberate_server/main.py` | Register new routers, call seeding on startup |
| `server/src/deliberate_server/policy/engine.py` | Load from DB, `invalidate_cache()`, remove file watcher |
| `server/src/deliberate_server/policy/directory.py` | Load from DB, `invalidate_cache()`, remove file watcher |
| `server/src/deliberate_server/api/routes/interrupts.py` | Add scope check |
| `server/src/deliberate_server/api/routes/approvals.py` | Add scope check + `?status=pending` filter |
| `server/src/deliberate_server/api/routes/ledger.py` | Add scope checks |
| `server/tests/conftest.py` | Seed `api_keys` table, add helper fixtures |
| `server/pyproject.toml` | No new deps needed (all deps already present) |
| `docker-compose.yml` | Add `SEED_FROM_YAML`, `ADMIN_BOOTSTRAP_KEY` env vars |
| `.env.example` | Add new env vars |
| `README.md` | Add Agent-Friendly section |
| `docs/quickstart.md` | Add API-based setup option |
| `docs/security.md` | Add RBAC section |

---

## Task 1: DB Models for RBAC and Admin

**Files:**
- Modify: `server/src/deliberate_server/db/models.py`
- Modify: `server/src/deliberate_server/auth.py`

- [ ] **Step 1: Add ApiKey model to models.py**

Open `server/src/deliberate_server/db/models.py` and add after the `Application` class:

```python
class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    application_id: Mapped[str] = mapped_column(
        Text, ForeignKey("applications.id"), nullable=False, default="default"
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    key_prefix: Mapped[str] = mapped_column(Text, nullable=False)
    key_hash: Mapped[str] = mapped_column(Text, nullable=False)
    scopes: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    created_by: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index("ix_api_keys_hash", "key_hash", unique=True),
        Index("ix_api_keys_app", "application_id"),
    )
```

Add the `ARRAY` import at the top:
```python
from sqlalchemy.dialects.postgresql import JSONB, UUID, ARRAY
```

- [ ] **Step 2: Add PolicyRecord and PolicyVersion models**

```python
class PolicyRecord(Base):
    __tablename__ = "policies"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    application_id: Mapped[str] = mapped_column(
        Text, ForeignKey("applications.id"), nullable=False, default="default"
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    definition: Mapped[dict] = mapped_column(JSONB, nullable=False)
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("application_id", "name", name="uq_policies_app_name"),
    )


class PolicyVersion(Base):
    __tablename__ = "policy_versions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    policy_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("policies.id"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    definition: Mapped[dict] = mapped_column(JSONB, nullable=False)
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    changed_by: Mapped[str] = mapped_column(Text, nullable=False)
    change_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_policy_versions_policy", "policy_id", "version", postgresql_using="btree"),
    )
```

Add imports: `Integer`, `Boolean`, `UniqueConstraint` from sqlalchemy.

- [ ] **Step 3: Add ApproverGroup model**

The `Approver` model already exists in models.py. Add `application_id`, `is_active`, `updated_at` columns to it, plus add `ApproverGroup`:

```python
class ApproverGroup(Base):
    __tablename__ = "approver_groups"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    application_id: Mapped[str] = mapped_column(
        Text, ForeignKey("applications.id"), nullable=False, default="default"
    )
    display_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    members: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_approver_groups_app", "application_id"),
    )
```

Also add to the existing `Approver` model (which already has `id`, `email`, `display_name`, `ooo_*` fields):
- `application_id` column (Text, FK, default="default")
- `is_active` column (Boolean, default=True)
- `updated_at` column (DateTime, server_default=func.now())

- [ ] **Step 4: Add `generate_api_key()` to auth.py**

Open `server/src/deliberate_server/auth.py` and add:

```python
import secrets

API_KEY_PREFIX = "dlb_ak_"

def generate_api_key() -> tuple[str, str, str]:
    """Generate a new API key. Returns (raw_key, key_prefix, key_hash)."""
    random_bytes = secrets.token_urlsafe(32)
    raw_key = f"{API_KEY_PREFIX}{random_bytes}"
    key_prefix = raw_key[:16]
    key_hash_value = hash_api_key(raw_key)
    return raw_key, key_prefix, key_hash_value
```

- [ ] **Step 5: Commit**

```bash
git add server/src/deliberate_server/db/models.py server/src/deliberate_server/auth.py
git commit -m "feat: add DB models for api_keys, policies, policy_versions, approver_groups"
```

---

## Task 2: Alembic Migration 0006

**Files:**
- Create: `server/alembic/versions/0006_agent_friendly.py`

- [ ] **Step 1: Generate migration stub**

```bash
cd server && uv run alembic revision -m "agent_friendly" --rev-id 0006
```

- [ ] **Step 2: Write migration upgrade**

Edit the generated file to contain:

```python
"""agent_friendly

Revision ID: 0006
Revises: 0005
Create Date: 2026-04-23
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB, ARRAY

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # api_keys table
    op.create_table(
        "api_keys",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("application_id", sa.Text(), sa.ForeignKey("applications.id"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("key_prefix", sa.Text(), nullable=False),
        sa.Column("key_hash", sa.Text(), nullable=False),
        sa.Column("scopes", ARRAY(sa.Text()), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_api_keys_hash", "api_keys", ["key_hash"], unique=True)
    op.create_index("ix_api_keys_app", "api_keys", ["application_id"])

    # policies table
    op.create_table(
        "policies",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("application_id", sa.Text(), sa.ForeignKey("applications.id"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("definition", JSONB(), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("application_id", "name", name="uq_policies_app_name"),
    )

    # policy_versions table
    op.create_table(
        "policy_versions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("policy_id", UUID(as_uuid=True), sa.ForeignKey("policies.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("definition", JSONB(), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("changed_by", sa.Text(), nullable=False),
        sa.Column("change_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_policy_versions_policy", "policy_versions", ["policy_id", sa.text("version DESC")])

    # approver_groups table
    op.create_table(
        "approver_groups",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("application_id", sa.Text(), sa.ForeignKey("applications.id"), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=True),
        sa.Column("members", ARRAY(sa.Text()), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_approver_groups_app", "approver_groups", ["application_id"])

    # Add columns to existing approvers table
    op.add_column("approvers", sa.Column("application_id", sa.Text(), sa.ForeignKey("applications.id"), nullable=True))
    op.add_column("approvers", sa.Column("is_active", sa.Boolean(), nullable=True, server_default=sa.text("true")))
    op.add_column("approvers", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True, server_default=sa.func.now()))

    # Backfill existing approvers
    op.execute("UPDATE approvers SET application_id = 'default', is_active = true, updated_at = now() WHERE application_id IS NULL")
    op.alter_column("approvers", "application_id", nullable=False)
    op.alter_column("approvers", "is_active", nullable=False)

    # Migrate existing API key from applications to api_keys
    op.execute("""
        INSERT INTO api_keys (id, application_id, name, key_prefix, key_hash, scopes, created_by, created_at)
        SELECT gen_random_uuid(), id, 'legacy-default', LEFT(api_key_hash, 16), api_key_hash,
               ARRAY['interrupts:write', 'approvals:read'],
               'migration-0006', now()
        FROM applications
        WHERE api_key_hash IS NOT NULL AND api_key_hash != ''
    """)


def downgrade() -> None:
    op.drop_table("policy_versions")
    op.drop_table("policies")
    op.drop_table("approver_groups")
    op.drop_table("api_keys")
    op.drop_column("approvers", "updated_at")
    op.drop_column("approvers", "is_active")
    op.drop_column("approvers", "application_id")
```

- [ ] **Step 3: Commit**

```bash
git add server/alembic/versions/0006_agent_friendly.py
git commit -m "feat: add migration 0006 for agent-friendly tables"
```

---

## Task 3: Auth Dependencies (Scope-Based RBAC)

**Files:**
- Create: `server/src/deliberate_server/api/deps.py`
- Create: `server/tests/test_rbac.py`

- [ ] **Step 1: Write failing tests for scope-based auth**

Create `server/tests/test_rbac.py`:

```python
"""Tests for scope-based RBAC auth dependencies."""
from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.anyio


async def test_request_without_api_key_returns_401(client: AsyncClient) -> None:
    """Endpoints requiring auth should reject requests without API key."""
    resp = await client.get("/policies")
    assert resp.status_code == 401
    assert "API key" in resp.json()["detail"]


async def test_request_with_revoked_key_returns_401(client: AsyncClient) -> None:
    """Revoked keys should be rejected."""
    # The default test key is active — we'll test revoked via the api_keys endpoint later
    resp = await client.get(
        "/policies",
        headers={"X-Deliberate-API-Key": "invalid-key-that-does-not-exist"},
    )
    assert resp.status_code == 401


async def test_request_with_insufficient_scope_returns_403(
    client: AsyncClient, agent_api_key: str
) -> None:
    """Agent key (interrupts:write, approvals:read) should not access policies:write."""
    resp = await client.post(
        "/policies",
        headers={"X-Deliberate-API-Key": agent_api_key},
        json={"name": "test", "matches": {}, "rules": []},
    )
    assert resp.status_code == 403
    assert "policies:write" in resp.json()["detail"]


async def test_request_with_correct_scope_succeeds(
    client: AsyncClient, admin_api_key: str
) -> None:
    """Admin key should access policies:read."""
    resp = await client.get(
        "/policies",
        headers={"X-Deliberate-API-Key": admin_api_key},
    )
    assert resp.status_code == 200
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd server && uv run pytest tests/test_rbac.py -v
```

Expected: FAIL — `deps.py` doesn't exist, fixtures `agent_api_key`/`admin_api_key` not defined.

- [ ] **Step 3: Create auth dependencies**

Create `server/src/deliberate_server/api/deps.py`:

```python
"""Auth dependencies for scope-based RBAC."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from deliberate_server.auth import hash_api_key
from deliberate_server.db.models import ApiKey
from deliberate_server.db.session import get_session


async def get_api_key(
    x_deliberate_api_key: Annotated[str, Header()],
    session: AsyncSession = Depends(get_session),
) -> ApiKey:
    """Authenticate via API key header. Returns the ApiKey row."""
    key_hash = hash_api_key(x_deliberate_api_key)
    result = await session.execute(
        select(ApiKey).where(
            ApiKey.key_hash == key_hash,
            ApiKey.revoked_at.is_(None),
        )
    )
    api_key = result.scalar_one_or_none()
    if api_key is None:
        raise HTTPException(status_code=401, detail="Invalid or revoked API key")

    if api_key.expires_at and api_key.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=401, detail="API key has expired")

    # Update last_used_at (fire and forget, don't block request)
    await session.execute(
        update(ApiKey)
        .where(ApiKey.id == api_key.id)
        .values(last_used_at=datetime.now(timezone.utc))
    )

    return api_key


def require_scope(scope: str):
    """Dependency factory that checks if the authenticated key has a given scope."""

    async def _check(api_key: ApiKey = Depends(get_api_key)) -> ApiKey:
        if scope not in api_key.scopes:
            raise HTTPException(
                status_code=403,
                detail=f"API key missing required scope: {scope}",
            )
        return api_key

    return _check
```

- [ ] **Step 4: Update conftest with api_key fixtures**

Add to `server/tests/conftest.py`, after the existing `client` fixture seed section where it creates the default application:

```python
from deliberate_server.auth import hash_api_key, generate_api_key
from deliberate_server.db.models import ApiKey

# Inside the client fixture, after seeding the default application:

# Seed admin API key
admin_raw, admin_prefix, admin_hash = generate_api_key()
admin_key_row = ApiKey(
    application_id="default",
    name="test-admin",
    key_prefix=admin_prefix,
    key_hash=admin_hash,
    scopes=[
        "interrupts:write", "approvals:read", "approvals:write",
        "policies:read", "policies:write",
        "approvers:read", "approvers:write",
        "api_keys:read", "api_keys:write",
        "ledger:read", "ledger:export",
    ],
    created_by="test",
)
session.add(admin_key_row)

# Seed agent API key
agent_raw, agent_prefix, agent_hash = generate_api_key()
agent_key_row = ApiKey(
    application_id="default",
    name="test-agent",
    key_prefix=agent_prefix,
    key_hash=agent_hash,
    scopes=["interrupts:write", "approvals:read"],
    created_by="test",
)
session.add(agent_key_row)
await session.flush()

# Also seed a legacy-compatible key matching existing test-api-key
legacy_hash = hash_api_key("test-api-key")
legacy_key_row = ApiKey(
    application_id="default",
    name="legacy-test",
    key_prefix="test-api-key"[:16],
    key_hash=legacy_hash,
    scopes=["interrupts:write", "approvals:read"],
    created_by="test",
)
session.add(legacy_key_row)
await session.flush()
```

Add fixtures that expose the raw keys:

```python
@pytest.fixture
def admin_api_key() -> str:
    """Returns raw admin API key for test requests."""
    # This needs to be coordinated with the client fixture
    # Store the raw keys as fixture-scoped values
    return _admin_raw_key

@pytest.fixture
def agent_api_key() -> str:
    return _agent_raw_key
```

Note: The exact implementation depends on how the existing `client` fixture manages its scope. The raw keys need to be accessible as separate fixtures. Use a module-level dict or wrap the client fixture to yield both the client and keys.

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd server && uv run pytest tests/test_rbac.py -v
```

Expected: All 4 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add server/src/deliberate_server/api/deps.py server/tests/test_rbac.py server/tests/conftest.py
git commit -m "feat: add scope-based RBAC auth dependencies with tests"
```

---

## Task 4: Config Updates

**Files:**
- Modify: `server/src/deliberate_server/config.py`
- Modify: `.env.example`

- [ ] **Step 1: Add new settings**

In `server/src/deliberate_server/config.py`, add to the `Settings` class:

```python
    # Seeding
    seed_from_yaml: bool = True

    # Admin bootstrap (set to create first admin key on startup)
    admin_bootstrap_key: str = ""
```

- [ ] **Step 2: Update .env.example**

Add to `.env.example`:

```bash
# Agent-Friendly Config (M5)
# Set to false to skip YAML seeding on startup
SEED_FROM_YAML=true
# Set a value to create an admin API key on first startup (logged once to stdout)
ADMIN_BOOTSTRAP_KEY=
```

- [ ] **Step 3: Commit**

```bash
git add server/src/deliberate_server/config.py .env.example
git commit -m "feat: add seed_from_yaml and admin_bootstrap_key settings"
```

---

## Task 5: Policy CRUD API

**Files:**
- Create: `server/src/deliberate_server/api/routes/policies.py`
- Create: `server/tests/test_policies_api.py`

- [ ] **Step 1: Write failing tests**

Create `server/tests/test_policies_api.py`:

```python
"""Tests for Policy CRUD API."""
from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.anyio

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


async def test_create_policy(client: AsyncClient, admin_api_key: str) -> None:
    resp = await client.post(
        "/policies",
        headers={"X-Deliberate-API-Key": admin_api_key},
        json=REFUND_POLICY,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "refund_approval"
    assert data["version"] == 1
    assert len(data["rules"]) == 2


async def test_create_duplicate_policy_returns_409(
    client: AsyncClient, admin_api_key: str
) -> None:
    headers = {"X-Deliberate-API-Key": admin_api_key}
    await client.post("/policies", headers=headers, json=REFUND_POLICY)
    resp = await client.post("/policies", headers=headers, json=REFUND_POLICY)
    assert resp.status_code == 409


async def test_list_policies(client: AsyncClient, admin_api_key: str) -> None:
    headers = {"X-Deliberate-API-Key": admin_api_key}
    await client.post("/policies", headers=headers, json=REFUND_POLICY)
    resp = await client.get("/policies", headers=headers)
    assert resp.status_code == 200
    policies = resp.json()
    assert len(policies) == 1
    assert policies[0]["name"] == "refund_approval"
    assert policies[0]["rule_count"] == 2


async def test_get_policy(client: AsyncClient, admin_api_key: str) -> None:
    headers = {"X-Deliberate-API-Key": admin_api_key}
    await client.post("/policies", headers=headers, json=REFUND_POLICY)
    resp = await client.get("/policies/refund_approval", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "refund_approval"
    assert data["definition"]["rules"][0]["name"] == "auto_small"


async def test_get_nonexistent_policy_returns_404(
    client: AsyncClient, admin_api_key: str
) -> None:
    resp = await client.get(
        "/policies/nope",
        headers={"X-Deliberate-API-Key": admin_api_key},
    )
    assert resp.status_code == 404


async def test_update_policy_increments_version(
    client: AsyncClient, admin_api_key: str
) -> None:
    headers = {"X-Deliberate-API-Key": admin_api_key}
    await client.post("/policies", headers=headers, json=REFUND_POLICY)

    updated = {**REFUND_POLICY, "rules": REFUND_POLICY["rules"][:1]}
    resp = await client.put(
        "/policies/refund_approval", headers=headers, json=updated
    )
    assert resp.status_code == 200
    assert resp.json()["version"] == 2


async def test_delete_policy(client: AsyncClient, admin_api_key: str) -> None:
    headers = {"X-Deliberate-API-Key": admin_api_key}
    await client.post("/policies", headers=headers, json=REFUND_POLICY)
    resp = await client.delete("/policies/refund_approval", headers=headers)
    assert resp.status_code == 204

    resp = await client.get("/policies/refund_approval", headers=headers)
    assert resp.status_code == 404


async def test_policy_test_endpoint(
    client: AsyncClient, admin_api_key: str
) -> None:
    headers = {"X-Deliberate-API-Key": admin_api_key}
    await client.post("/policies", headers=headers, json=REFUND_POLICY)
    resp = await client.post(
        "/policies/refund_approval/test",
        headers=headers,
        json={
            "layout": "financial_decision",
            "subject": "Refund Request",
            "amount": {"value": 50, "currency": "USD"},
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["matched_rule"] == "auto_small"
    assert data["action"] == "auto_approve"


async def test_policy_versions(client: AsyncClient, admin_api_key: str) -> None:
    headers = {"X-Deliberate-API-Key": admin_api_key}
    await client.post("/policies", headers=headers, json=REFUND_POLICY)

    updated = {**REFUND_POLICY, "rules": REFUND_POLICY["rules"][:1]}
    await client.put("/policies/refund_approval", headers=headers, json=updated)

    resp = await client.get("/policies/refund_approval/versions", headers=headers)
    assert resp.status_code == 200
    versions = resp.json()
    assert len(versions) == 2
    assert versions[0]["version"] == 2
    assert versions[1]["version"] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd server && uv run pytest tests/test_policies_api.py -v
```

Expected: FAIL — `routes/policies.py` doesn't exist.

- [ ] **Step 3: Implement Policy CRUD routes**

Create `server/src/deliberate_server/api/routes/policies.py`:

```python
"""Policy CRUD API routes."""
from __future__ import annotations

import hashlib
import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from deliberate_server.api.deps import require_scope
from deliberate_server.db.models import ApiKey, PolicyRecord, PolicyVersion
from deliberate_server.db.session import get_session
from deliberate_server.policy.engine import PolicyEngine
from deliberate_server.policy.expression import evaluate

router = APIRouter(prefix="/policies", tags=["policies"])

MAX_VERSIONS_PER_POLICY = 50


class PolicyCreateRequest(BaseModel):
    name: str
    matches: dict[str, Any] = {}
    rules: list[dict[str, Any]]


class PolicyUpdateRequest(BaseModel):
    matches: dict[str, Any] = {}
    rules: list[dict[str, Any]]
    change_reason: str | None = None


def _hash_definition(definition: dict) -> str:
    canonical = json.dumps(definition, sort_keys=True, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(canonical.encode()).hexdigest()}"


@router.get("")
async def list_policies(
    _key: ApiKey = Depends(require_scope("policies:read")),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    result = await session.execute(
        select(PolicyRecord).where(PolicyRecord.is_active.is_(True))
    )
    policies = result.scalars().all()
    return [
        {
            "name": p.name,
            "version": p.version,
            "rule_count": len(p.definition.get("rules", [])),
            "content_hash": p.content_hash,
            "updated_at": p.updated_at.isoformat(),
        }
        for p in policies
    ]


@router.get("/{name}")
async def get_policy(
    name: str,
    _key: ApiKey = Depends(require_scope("policies:read")),
    session: AsyncSession = Depends(get_session),
) -> dict:
    result = await session.execute(
        select(PolicyRecord).where(
            PolicyRecord.name == name, PolicyRecord.is_active.is_(True)
        )
    )
    policy = result.scalar_one_or_none()
    if policy is None:
        raise HTTPException(status_code=404, detail=f"Policy '{name}' not found")
    return {
        "name": policy.name,
        "version": policy.version,
        "definition": policy.definition,
        "content_hash": policy.content_hash,
        "created_by": policy.created_by,
        "created_at": policy.created_at.isoformat(),
        "updated_at": policy.updated_at.isoformat(),
    }


@router.post("", status_code=201)
async def create_policy(
    body: PolicyCreateRequest,
    key: ApiKey = Depends(require_scope("policies:write")),
    session: AsyncSession = Depends(get_session),
) -> dict:
    # Check for duplicate
    existing = await session.execute(
        select(PolicyRecord).where(PolicyRecord.name == body.name)
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail=f"Policy '{body.name}' already exists")

    definition = {"name": body.name, "matches": body.matches, "rules": body.rules}
    content_hash = _hash_definition(definition)

    policy = PolicyRecord(
        application_id=key.application_id,
        name=body.name,
        version=1,
        definition=definition,
        content_hash=content_hash,
        created_by=key.name,
    )
    session.add(policy)
    await session.flush()

    # Save initial version
    version = PolicyVersion(
        policy_id=policy.id,
        version=1,
        definition=definition,
        content_hash=content_hash,
        changed_by=key.name,
        change_reason="Initial creation",
    )
    session.add(version)
    await session.commit()

    # Invalidate policy engine cache
    from deliberate_server.main import get_policy_engine
    engine = get_policy_engine()
    if engine:
        engine.invalidate_cache()

    return {
        "name": policy.name,
        "version": policy.version,
        "rules": body.rules,
        "content_hash": content_hash,
    }


@router.put("/{name}")
async def update_policy(
    name: str,
    body: PolicyUpdateRequest,
    key: ApiKey = Depends(require_scope("policies:write")),
    session: AsyncSession = Depends(get_session),
) -> dict:
    result = await session.execute(
        select(PolicyRecord).where(
            PolicyRecord.name == name, PolicyRecord.is_active.is_(True)
        )
    )
    policy = result.scalar_one_or_none()
    if policy is None:
        raise HTTPException(status_code=404, detail=f"Policy '{name}' not found")

    definition = {"name": name, "matches": body.matches, "rules": body.rules}
    content_hash = _hash_definition(definition)
    new_version = policy.version + 1

    policy.definition = definition
    policy.content_hash = content_hash
    policy.version = new_version
    policy.updated_at = func.now()

    # Save version history
    version = PolicyVersion(
        policy_id=policy.id,
        version=new_version,
        definition=definition,
        content_hash=content_hash,
        changed_by=key.name,
        change_reason=body.change_reason,
    )
    session.add(version)

    # Trim old versions if over limit
    count_result = await session.execute(
        select(func.count()).select_from(PolicyVersion).where(
            PolicyVersion.policy_id == policy.id
        )
    )
    version_count = count_result.scalar_one()
    if version_count > MAX_VERSIONS_PER_POLICY:
        oldest = await session.execute(
            select(PolicyVersion.id)
            .where(PolicyVersion.policy_id == policy.id)
            .order_by(PolicyVersion.version.asc())
            .limit(version_count - MAX_VERSIONS_PER_POLICY)
        )
        old_ids = [row[0] for row in oldest.all()]
        if old_ids:
            await session.execute(
                delete(PolicyVersion).where(PolicyVersion.id.in_(old_ids))
            )

    await session.commit()

    from deliberate_server.main import get_policy_engine
    engine = get_policy_engine()
    if engine:
        engine.invalidate_cache()

    return {
        "name": name,
        "version": new_version,
        "rules": body.rules,
        "content_hash": content_hash,
    }


@router.delete("/{name}", status_code=204)
async def delete_policy(
    name: str,
    _key: ApiKey = Depends(require_scope("policies:write")),
    session: AsyncSession = Depends(get_session),
) -> None:
    result = await session.execute(
        select(PolicyRecord).where(
            PolicyRecord.name == name, PolicyRecord.is_active.is_(True)
        )
    )
    policy = result.scalar_one_or_none()
    if policy is None:
        raise HTTPException(status_code=404, detail=f"Policy '{name}' not found")

    policy.is_active = False
    policy.updated_at = func.now()
    await session.commit()

    from deliberate_server.main import get_policy_engine
    engine = get_policy_engine()
    if engine:
        engine.invalidate_cache()


@router.post("/{name}/test")
async def test_policy(
    name: str,
    body: dict,
    _key: ApiKey = Depends(require_scope("policies:read")),
    session: AsyncSession = Depends(get_session),
) -> dict:
    result = await session.execute(
        select(PolicyRecord).where(
            PolicyRecord.name == name, PolicyRecord.is_active.is_(True)
        )
    )
    policy = result.scalar_one_or_none()
    if policy is None:
        raise HTTPException(status_code=404, detail=f"Policy '{name}' not found")

    definition = policy.definition
    matched_rule = None
    for rule in definition.get("rules", []):
        expr = rule.get("when", "true")
        if evaluate(expr, body):
            matched_rule = rule
            break

    if matched_rule is None:
        return {"matched": False, "matched_rule": None, "action": None}

    return {
        "matched": True,
        "matched_rule": matched_rule["name"],
        "action": matched_rule.get("action", "request_human"),
        "approvers": matched_rule.get("approvers"),
        "timeout": matched_rule.get("timeout"),
    }


@router.get("/{name}/versions")
async def list_policy_versions(
    name: str,
    _key: ApiKey = Depends(require_scope("policies:read")),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    # First verify policy exists
    policy_result = await session.execute(
        select(PolicyRecord).where(PolicyRecord.name == name)
    )
    policy = policy_result.scalar_one_or_none()
    if policy is None:
        raise HTTPException(status_code=404, detail=f"Policy '{name}' not found")

    result = await session.execute(
        select(PolicyVersion)
        .where(PolicyVersion.policy_id == policy.id)
        .order_by(PolicyVersion.version.desc())
    )
    versions = result.scalars().all()
    return [
        {
            "version": v.version,
            "content_hash": v.content_hash,
            "changed_by": v.changed_by,
            "change_reason": v.change_reason,
            "created_at": v.created_at.isoformat(),
        }
        for v in versions
    ]
```

- [ ] **Step 4: Register router in main.py**

Add to `server/src/deliberate_server/main.py`:

```python
from deliberate_server.api.routes.policies import router as policies_router

app.include_router(policies_router)
```

Also add a module-level `_policy_engine` reference and `get_policy_engine()` accessor:

```python
_policy_engine: PolicyEngine | None = None

def get_policy_engine() -> PolicyEngine | None:
    return _policy_engine
```

Set `_policy_engine` in the lifespan function where `init_policy_system()` is called.

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd server && uv run pytest tests/test_policies_api.py -v
```

Expected: All 9 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add server/src/deliberate_server/api/routes/policies.py server/tests/test_policies_api.py server/src/deliberate_server/main.py
git commit -m "feat: add policy CRUD API with tests"
```

---

## Task 6: Approver & Group CRUD API

**Files:**
- Create: `server/src/deliberate_server/api/routes/approvers_admin.py`
- Create: `server/tests/test_approvers_api.py`

- [ ] **Step 1: Write failing tests**

Create `server/tests/test_approvers_api.py`:

```python
"""Tests for Approver and Group CRUD API."""
from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.anyio


async def test_create_approver(client: AsyncClient, admin_api_key: str) -> None:
    resp = await client.post(
        "/approvers",
        headers={"X-Deliberate-API-Key": admin_api_key},
        json={"id": "eng_lead", "email": "eng@example.com", "display_name": "Engineer Lead"},
    )
    assert resp.status_code == 201
    assert resp.json()["id"] == "eng_lead"


async def test_create_duplicate_approver_returns_409(
    client: AsyncClient, admin_api_key: str
) -> None:
    headers = {"X-Deliberate-API-Key": admin_api_key}
    await client.post(
        "/approvers", headers=headers,
        json={"id": "eng_lead", "email": "eng@example.com"},
    )
    resp = await client.post(
        "/approvers", headers=headers,
        json={"id": "eng_lead", "email": "other@example.com"},
    )
    assert resp.status_code == 409


async def test_list_approvers(client: AsyncClient, admin_api_key: str) -> None:
    headers = {"X-Deliberate-API-Key": admin_api_key}
    await client.post(
        "/approvers", headers=headers,
        json={"id": "eng_lead", "email": "eng@example.com"},
    )
    resp = await client.get("/approvers", headers=headers)
    assert resp.status_code == 200
    assert any(a["id"] == "eng_lead" for a in resp.json())


async def test_get_approver(client: AsyncClient, admin_api_key: str) -> None:
    headers = {"X-Deliberate-API-Key": admin_api_key}
    await client.post(
        "/approvers", headers=headers,
        json={"id": "eng_lead", "email": "eng@example.com"},
    )
    resp = await client.get("/approvers/eng_lead", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["email"] == "eng@example.com"


async def test_update_approver(client: AsyncClient, admin_api_key: str) -> None:
    headers = {"X-Deliberate-API-Key": admin_api_key}
    await client.post(
        "/approvers", headers=headers,
        json={"id": "eng_lead", "email": "eng@example.com"},
    )
    resp = await client.put(
        "/approvers/eng_lead", headers=headers,
        json={"email": "new@example.com", "ooo_active": True},
    )
    assert resp.status_code == 200
    assert resp.json()["email"] == "new@example.com"
    assert resp.json()["ooo_active"] is True


async def test_delete_approver(client: AsyncClient, admin_api_key: str) -> None:
    headers = {"X-Deliberate-API-Key": admin_api_key}
    await client.post(
        "/approvers", headers=headers,
        json={"id": "eng_lead", "email": "eng@example.com"},
    )
    resp = await client.delete("/approvers/eng_lead", headers=headers)
    assert resp.status_code == 204
    resp = await client.get("/approvers/eng_lead", headers=headers)
    assert resp.status_code == 404


async def test_create_group(client: AsyncClient, admin_api_key: str) -> None:
    headers = {"X-Deliberate-API-Key": admin_api_key}
    # Create approvers first
    await client.post(
        "/approvers", headers=headers,
        json={"id": "eng1", "email": "eng1@example.com"},
    )
    await client.post(
        "/approvers", headers=headers,
        json={"id": "eng2", "email": "eng2@example.com"},
    )
    resp = await client.post(
        "/groups", headers=headers,
        json={"id": "eng_team", "members": ["eng1", "eng2"]},
    )
    assert resp.status_code == 201
    assert resp.json()["members"] == ["eng1", "eng2"]


async def test_create_group_with_invalid_member_returns_400(
    client: AsyncClient, admin_api_key: str
) -> None:
    headers = {"X-Deliberate-API-Key": admin_api_key}
    resp = await client.post(
        "/groups", headers=headers,
        json={"id": "bad_team", "members": ["nonexistent"]},
    )
    assert resp.status_code == 400
    assert "nonexistent" in resp.json()["detail"]


async def test_list_groups(client: AsyncClient, admin_api_key: str) -> None:
    headers = {"X-Deliberate-API-Key": admin_api_key}
    await client.post(
        "/approvers", headers=headers,
        json={"id": "eng1", "email": "eng1@example.com"},
    )
    await client.post(
        "/groups", headers=headers,
        json={"id": "eng_team", "members": ["eng1"]},
    )
    resp = await client.get("/groups", headers=headers)
    assert resp.status_code == 200
    assert any(g["id"] == "eng_team" for g in resp.json())


async def test_update_group(client: AsyncClient, admin_api_key: str) -> None:
    headers = {"X-Deliberate-API-Key": admin_api_key}
    await client.post(
        "/approvers", headers=headers,
        json={"id": "eng1", "email": "eng1@example.com"},
    )
    await client.post(
        "/approvers", headers=headers,
        json={"id": "eng2", "email": "eng2@example.com"},
    )
    await client.post(
        "/groups", headers=headers,
        json={"id": "eng_team", "members": ["eng1"]},
    )
    resp = await client.put(
        "/groups/eng_team", headers=headers,
        json={"members": ["eng1", "eng2"]},
    )
    assert resp.status_code == 200
    assert resp.json()["members"] == ["eng1", "eng2"]


async def test_delete_group(client: AsyncClient, admin_api_key: str) -> None:
    headers = {"X-Deliberate-API-Key": admin_api_key}
    await client.post(
        "/approvers", headers=headers,
        json={"id": "eng1", "email": "eng1@example.com"},
    )
    await client.post(
        "/groups", headers=headers,
        json={"id": "eng_team", "members": ["eng1"]},
    )
    resp = await client.delete("/groups/eng_team", headers=headers)
    assert resp.status_code == 204
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd server && uv run pytest tests/test_approvers_api.py -v
```

- [ ] **Step 3: Implement Approver and Group CRUD routes**

Create `server/src/deliberate_server/api/routes/approvers_admin.py`:

```python
"""Approver and Group CRUD API routes."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from deliberate_server.api.deps import require_scope
from deliberate_server.db.models import ApiKey, Approver, ApproverGroup
from deliberate_server.db.session import get_session

approver_router = APIRouter(prefix="/approvers", tags=["approvers"])
group_router = APIRouter(prefix="/groups", tags=["approvers"])


# --- Request models ---

class ApproverCreateRequest(BaseModel):
    id: str
    email: str
    display_name: str | None = None


class ApproverUpdateRequest(BaseModel):
    email: str | None = None
    display_name: str | None = None
    ooo_active: bool | None = None
    ooo_from: str | None = None
    ooo_until: str | None = None
    ooo_delegate_to: str | None = None


class GroupCreateRequest(BaseModel):
    id: str
    display_name: str | None = None
    members: list[str]


class GroupUpdateRequest(BaseModel):
    display_name: str | None = None
    members: list[str] | None = None


# --- Approver endpoints ---

@approver_router.get("")
async def list_approvers(
    _key: ApiKey = Depends(require_scope("approvers:read")),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    result = await session.execute(
        select(Approver).where(Approver.is_active.is_(True))
    )
    return [
        {
            "id": a.id,
            "email": a.email,
            "display_name": a.display_name,
            "ooo_active": a.ooo_active,
        }
        for a in result.scalars().all()
    ]


@approver_router.get("/{approver_id}")
async def get_approver(
    approver_id: str,
    _key: ApiKey = Depends(require_scope("approvers:read")),
    session: AsyncSession = Depends(get_session),
) -> dict:
    result = await session.execute(
        select(Approver).where(
            Approver.id == approver_id, Approver.is_active.is_(True)
        )
    )
    approver = result.scalar_one_or_none()
    if approver is None:
        raise HTTPException(status_code=404, detail=f"Approver '{approver_id}' not found")
    return {
        "id": approver.id,
        "email": approver.email,
        "display_name": approver.display_name,
        "ooo_active": approver.ooo_active,
        "ooo_from": approver.ooo_from.isoformat() if approver.ooo_from else None,
        "ooo_until": approver.ooo_until.isoformat() if approver.ooo_until else None,
        "ooo_delegate_to": approver.ooo_delegate_to,
    }


@approver_router.post("", status_code=201)
async def create_approver(
    body: ApproverCreateRequest,
    key: ApiKey = Depends(require_scope("approvers:write")),
    session: AsyncSession = Depends(get_session),
) -> dict:
    existing = await session.execute(
        select(Approver).where(Approver.id == body.id)
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail=f"Approver '{body.id}' already exists")

    approver = Approver(
        id=body.id,
        application_id=key.application_id,
        email=body.email,
        display_name=body.display_name,
    )
    session.add(approver)
    await session.commit()

    from deliberate_server.main import get_approver_directory
    directory = get_approver_directory()
    if directory:
        directory.invalidate_cache()

    return {"id": approver.id, "email": approver.email, "display_name": approver.display_name}


@approver_router.put("/{approver_id}")
async def update_approver(
    approver_id: str,
    body: ApproverUpdateRequest,
    _key: ApiKey = Depends(require_scope("approvers:write")),
    session: AsyncSession = Depends(get_session),
) -> dict:
    result = await session.execute(
        select(Approver).where(
            Approver.id == approver_id, Approver.is_active.is_(True)
        )
    )
    approver = result.scalar_one_or_none()
    if approver is None:
        raise HTTPException(status_code=404, detail=f"Approver '{approver_id}' not found")

    update_fields = body.model_dump(exclude_unset=True)
    for field, value in update_fields.items():
        setattr(approver, field, value)
    approver.updated_at = func.now()
    await session.commit()

    from deliberate_server.main import get_approver_directory
    directory = get_approver_directory()
    if directory:
        directory.invalidate_cache()

    return {
        "id": approver.id,
        "email": approver.email,
        "display_name": approver.display_name,
        "ooo_active": approver.ooo_active,
    }


@approver_router.delete("/{approver_id}", status_code=204)
async def delete_approver(
    approver_id: str,
    _key: ApiKey = Depends(require_scope("approvers:write")),
    session: AsyncSession = Depends(get_session),
) -> None:
    result = await session.execute(
        select(Approver).where(
            Approver.id == approver_id, Approver.is_active.is_(True)
        )
    )
    approver = result.scalar_one_or_none()
    if approver is None:
        raise HTTPException(status_code=404, detail=f"Approver '{approver_id}' not found")

    approver.is_active = False
    approver.updated_at = func.now()
    await session.commit()

    from deliberate_server.main import get_approver_directory
    directory = get_approver_directory()
    if directory:
        directory.invalidate_cache()


# --- Group endpoints ---

async def _validate_members(
    members: list[str], session: AsyncSession
) -> None:
    """Verify all member IDs exist as active approvers."""
    result = await session.execute(
        select(Approver.id).where(
            Approver.id.in_(members), Approver.is_active.is_(True)
        )
    )
    found = {row[0] for row in result.all()}
    missing = set(members) - found
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown approver IDs: {', '.join(sorted(missing))}",
        )


@group_router.get("")
async def list_groups(
    _key: ApiKey = Depends(require_scope("approvers:read")),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    result = await session.execute(
        select(ApproverGroup).where(ApproverGroup.is_active.is_(True))
    )
    return [
        {"id": g.id, "display_name": g.display_name, "members": g.members}
        for g in result.scalars().all()
    ]


@group_router.post("", status_code=201)
async def create_group(
    body: GroupCreateRequest,
    key: ApiKey = Depends(require_scope("approvers:write")),
    session: AsyncSession = Depends(get_session),
) -> dict:
    existing = await session.execute(
        select(ApproverGroup).where(ApproverGroup.id == body.id)
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail=f"Group '{body.id}' already exists")

    await _validate_members(body.members, session)

    group = ApproverGroup(
        id=body.id,
        application_id=key.application_id,
        display_name=body.display_name,
        members=body.members,
    )
    session.add(group)
    await session.commit()

    from deliberate_server.main import get_approver_directory
    directory = get_approver_directory()
    if directory:
        directory.invalidate_cache()

    return {"id": group.id, "display_name": group.display_name, "members": group.members}


@group_router.put("/{group_id}")
async def update_group(
    group_id: str,
    body: GroupUpdateRequest,
    _key: ApiKey = Depends(require_scope("approvers:write")),
    session: AsyncSession = Depends(get_session),
) -> dict:
    result = await session.execute(
        select(ApproverGroup).where(
            ApproverGroup.id == group_id, ApproverGroup.is_active.is_(True)
        )
    )
    group = result.scalar_one_or_none()
    if group is None:
        raise HTTPException(status_code=404, detail=f"Group '{group_id}' not found")

    if body.members is not None:
        await _validate_members(body.members, session)
        group.members = body.members
    if body.display_name is not None:
        group.display_name = body.display_name
    group.updated_at = func.now()
    await session.commit()

    from deliberate_server.main import get_approver_directory
    directory = get_approver_directory()
    if directory:
        directory.invalidate_cache()

    return {"id": group.id, "display_name": group.display_name, "members": group.members}


@group_router.delete("/{group_id}", status_code=204)
async def delete_group(
    group_id: str,
    _key: ApiKey = Depends(require_scope("approvers:write")),
    session: AsyncSession = Depends(get_session),
) -> None:
    result = await session.execute(
        select(ApproverGroup).where(
            ApproverGroup.id == group_id, ApproverGroup.is_active.is_(True)
        )
    )
    group = result.scalar_one_or_none()
    if group is None:
        raise HTTPException(status_code=404, detail=f"Group '{group_id}' not found")

    group.is_active = False
    group.updated_at = func.now()
    await session.commit()

    from deliberate_server.main import get_approver_directory
    directory = get_approver_directory()
    if directory:
        directory.invalidate_cache()
```

- [ ] **Step 4: Register routers in main.py**

```python
from deliberate_server.api.routes.approvers_admin import approver_router, group_router

app.include_router(approver_router)
app.include_router(group_router)
```

Also add `get_approver_directory()` accessor similar to `get_policy_engine()`.

- [ ] **Step 5: Run tests**

```bash
cd server && uv run pytest tests/test_approvers_api.py -v
```

Expected: All 11 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add server/src/deliberate_server/api/routes/approvers_admin.py server/tests/test_approvers_api.py server/src/deliberate_server/main.py
git commit -m "feat: add approver and group CRUD API with tests"
```

---

## Task 7: API Key Management Endpoints

**Files:**
- Create: `server/src/deliberate_server/api/routes/api_keys.py`
- Create: `server/tests/test_api_keys.py`

- [ ] **Step 1: Write failing tests**

Create `server/tests/test_api_keys.py`:

```python
"""Tests for API Key management endpoints."""
from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.anyio


async def test_create_api_key(client: AsyncClient, admin_api_key: str) -> None:
    resp = await client.post(
        "/api-keys",
        headers={"X-Deliberate-API-Key": admin_api_key},
        json={
            "name": "new-agent",
            "scopes": ["interrupts:write", "approvals:read"],
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "new-agent"
    assert data["raw_key"].startswith("dlb_ak_")
    assert "key_prefix" in data
    assert data["scopes"] == ["interrupts:write", "approvals:read"]


async def test_created_key_works(client: AsyncClient, admin_api_key: str) -> None:
    resp = await client.post(
        "/api-keys",
        headers={"X-Deliberate-API-Key": admin_api_key},
        json={"name": "reader", "scopes": ["policies:read"]},
    )
    new_key = resp.json()["raw_key"]
    resp = await client.get(
        "/policies",
        headers={"X-Deliberate-API-Key": new_key},
    )
    assert resp.status_code == 200


async def test_list_api_keys(client: AsyncClient, admin_api_key: str) -> None:
    resp = await client.get(
        "/api-keys",
        headers={"X-Deliberate-API-Key": admin_api_key},
    )
    assert resp.status_code == 200
    keys = resp.json()
    assert len(keys) >= 1
    # raw_key must NOT be in the response
    for key in keys:
        assert "raw_key" not in key
        assert "key_hash" not in key
        assert "key_prefix" in key


async def test_revoke_api_key(client: AsyncClient, admin_api_key: str) -> None:
    # Create a key
    resp = await client.post(
        "/api-keys",
        headers={"X-Deliberate-API-Key": admin_api_key},
        json={"name": "to-revoke", "scopes": ["policies:read"]},
    )
    key_id = resp.json()["id"]
    raw_key = resp.json()["raw_key"]

    # Revoke it
    resp = await client.delete(
        f"/api-keys/{key_id}",
        headers={"X-Deliberate-API-Key": admin_api_key},
    )
    assert resp.status_code == 204

    # Verify it no longer works
    resp = await client.get(
        "/policies",
        headers={"X-Deliberate-API-Key": raw_key},
    )
    assert resp.status_code == 401
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd server && uv run pytest tests/test_api_keys.py -v
```

- [ ] **Step 3: Implement API Key management routes**

Create `server/src/deliberate_server/api/routes/api_keys.py`:

```python
"""API Key management routes."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from deliberate_server.api.deps import require_scope
from deliberate_server.auth import generate_api_key
from deliberate_server.db.models import ApiKey
from deliberate_server.db.session import get_session

router = APIRouter(prefix="/api-keys", tags=["api-keys"])

ALL_SCOPES = [
    "interrupts:write", "approvals:read", "approvals:write",
    "policies:read", "policies:write",
    "approvers:read", "approvers:write",
    "api_keys:read", "api_keys:write",
    "ledger:read", "ledger:export",
]

PREDEFINED_ROLES = {
    "agent": ["interrupts:write", "approvals:read"],
    "admin": ALL_SCOPES,
    "readonly": ["policies:read", "approvers:read", "ledger:read"],
    "operator": ["approvers:read", "approvers:write", "policies:read", "api_keys:read"],
}


class ApiKeyCreateRequest(BaseModel):
    name: str
    scopes: list[str] | None = None
    role: str | None = None  # convenience: "agent", "admin", "readonly", "operator"
    expires_at: str | None = None


@router.get("")
async def list_api_keys(
    _key: ApiKey = Depends(require_scope("api_keys:read")),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    result = await session.execute(
        select(ApiKey).where(ApiKey.revoked_at.is_(None))
    )
    return [
        {
            "id": str(k.id),
            "name": k.name,
            "key_prefix": k.key_prefix,
            "scopes": k.scopes,
            "created_by": k.created_by,
            "created_at": k.created_at.isoformat(),
            "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
        }
        for k in result.scalars().all()
    ]


@router.post("", status_code=201)
async def create_api_key(
    body: ApiKeyCreateRequest,
    key: ApiKey = Depends(require_scope("api_keys:write")),
    session: AsyncSession = Depends(get_session),
) -> dict:
    # Resolve scopes from role or explicit list
    if body.role and body.role in PREDEFINED_ROLES:
        scopes = PREDEFINED_ROLES[body.role]
    elif body.scopes:
        invalid = set(body.scopes) - set(ALL_SCOPES)
        if invalid:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid scopes: {', '.join(sorted(invalid))}",
            )
        scopes = body.scopes
    else:
        raise HTTPException(
            status_code=400,
            detail="Provide either 'scopes' or 'role'",
        )

    raw_key, key_prefix, key_hash = generate_api_key()

    api_key = ApiKey(
        application_id=key.application_id,
        name=body.name,
        key_prefix=key_prefix,
        key_hash=key_hash,
        scopes=scopes,
        created_by=key.name,
    )
    session.add(api_key)
    await session.commit()

    return {
        "id": str(api_key.id),
        "name": api_key.name,
        "key_prefix": key_prefix,
        "raw_key": raw_key,  # returned ONCE only
        "scopes": scopes,
    }


@router.delete("/{key_id}", status_code=204)
async def revoke_api_key(
    key_id: str,
    _key: ApiKey = Depends(require_scope("api_keys:write")),
    session: AsyncSession = Depends(get_session),
) -> None:
    result = await session.execute(
        select(ApiKey).where(ApiKey.id == key_id, ApiKey.revoked_at.is_(None))
    )
    api_key = result.scalar_one_or_none()
    if api_key is None:
        raise HTTPException(status_code=404, detail="API key not found")

    api_key.revoked_at = datetime.now(timezone.utc)
    await session.commit()
```

- [ ] **Step 4: Register router in main.py**

```python
from deliberate_server.api.routes.api_keys import router as api_keys_router

app.include_router(api_keys_router)
```

- [ ] **Step 5: Run tests**

```bash
cd server && uv run pytest tests/test_api_keys.py -v
```

Expected: All 4 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add server/src/deliberate_server/api/routes/api_keys.py server/tests/test_api_keys.py server/src/deliberate_server/main.py
git commit -m "feat: add API key management endpoints with tests"
```

---

## Task 8: PolicyEngine and ApproverDirectory — DB Loading

**Files:**
- Modify: `server/src/deliberate_server/policy/engine.py`
- Modify: `server/src/deliberate_server/policy/directory.py`

- [ ] **Step 1: Add `invalidate_cache()` and `load_from_db()` to PolicyEngine**

In `server/src/deliberate_server/policy/engine.py`, add methods:

```python
async def load_from_db(self, session: AsyncSession) -> None:
    """Load active policies from database."""
    from deliberate_server.db.models import PolicyRecord
    result = await session.execute(
        select(PolicyRecord).where(PolicyRecord.is_active.is_(True))
    )
    policies = result.scalars().all()
    loaded = []
    for p in policies:
        definition = p.definition
        # Parse the same way YAML policies are parsed
        parsed = Policy(**definition)
        loaded.append((parsed, p.content_hash))
    self._policies = loaded
    self._cache_valid = True

def invalidate_cache(self) -> None:
    """Mark cache as stale. Next evaluate() will reload from DB."""
    self._cache_valid = False
```

Modify `evaluate()` to check `_cache_valid` and reload if needed. The reload requires an async DB session, so `evaluate()` needs to accept one or the engine needs a reference to the session factory.

Pattern: Store a reference to the session factory in the engine, and if `_cache_valid` is False at `evaluate()` time, reload synchronously in a new session.

```python
async def evaluate(self, payload: dict, session: AsyncSession | None = None) -> ResolvedPlan:
    if not self._cache_valid and session is not None:
        await self.load_from_db(session)
    # ... existing evaluate logic unchanged ...
```

- [ ] **Step 2: Add `invalidate_cache()` and `load_from_db()` to ApproverDirectory**

In `server/src/deliberate_server/policy/directory.py`, add:

```python
async def load_from_db(self, session: AsyncSession) -> None:
    """Load active approvers and groups from database."""
    from deliberate_server.db.models import Approver as ApproverModel
    from deliberate_server.db.models import ApproverGroup as GroupModel

    approver_result = await session.execute(
        select(ApproverModel).where(ApproverModel.is_active.is_(True))
    )
    approvers = {}
    for a in approver_result.scalars().all():
        approvers[a.id] = ApproverEntry(
            id=a.id,
            email=a.email,
            display_name=a.display_name or "",
            out_of_office=OutOfOffice(active=a.ooo_active),
        )

    group_result = await session.execute(
        select(GroupModel).where(GroupModel.is_active.is_(True))
    )
    groups = {}
    for g in group_result.scalars().all():
        groups[g.id] = ApproverGroup(id=g.id, members=list(g.members))

    with self._lock:
        self._approvers = approvers
        self._groups = groups
        self._cache_valid = True

def invalidate_cache(self) -> None:
    self._cache_valid = False
```

- [ ] **Step 3: Remove file-watching threads**

Remove `start_watching()` and `stop_watching()` methods from both `PolicyEngine` and `ApproverDirectory` (or keep as no-ops for backward compat). Remove the background polling thread that checks file hashes.

- [ ] **Step 4: Commit**

```bash
git add server/src/deliberate_server/policy/engine.py server/src/deliberate_server/policy/directory.py
git commit -m "feat: policy engine and approver directory load from DB with cache invalidation"
```

---

## Task 9: YAML Seeding and Bootstrap

**Files:**
- Create: `server/src/deliberate_server/seeding.py`
- Create: `server/tests/test_seeding.py`

- [ ] **Step 1: Write failing tests**

Create `server/tests/test_seeding.py`:

```python
"""Tests for YAML seeding logic."""
from __future__ import annotations

import pytest
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from deliberate_server.db.models import PolicyRecord, Approver, ApproverGroup, ApiKey
from deliberate_server.seeding import seed_from_yaml_if_empty, bootstrap_admin_key

pytestmark = pytest.mark.anyio


async def test_seed_policies_when_empty(db_session: AsyncSession) -> None:
    """Seeds policies from YAML when DB has none."""
    await seed_from_yaml_if_empty(
        db_session,
        policies_dir="examples/policies",
        approvers_file="config/approvers.yaml",
    )
    result = await db_session.execute(select(func.count()).select_from(PolicyRecord))
    assert result.scalar_one() == 2  # default.yaml + refund.yaml


async def test_seed_does_not_overwrite(db_session: AsyncSession) -> None:
    """Does NOT seed if DB already has policies."""
    # Insert one policy first
    db_session.add(PolicyRecord(
        application_id="default", name="existing", version=1,
        definition={"name": "existing", "rules": []},
        content_hash="sha256:test", created_by="test",
    ))
    await db_session.flush()

    await seed_from_yaml_if_empty(
        db_session,
        policies_dir="examples/policies",
        approvers_file="config/approvers.yaml",
    )
    result = await db_session.execute(select(func.count()).select_from(PolicyRecord))
    assert result.scalar_one() == 1  # Only the existing one


async def test_seed_approvers(db_session: AsyncSession) -> None:
    await seed_from_yaml_if_empty(
        db_session,
        policies_dir="examples/policies",
        approvers_file="config/approvers.yaml",
    )
    result = await db_session.execute(select(func.count()).select_from(Approver))
    assert result.scalar_one() == 2  # finance_lead + cfo

    groups = await db_session.execute(select(func.count()).select_from(ApproverGroup))
    assert groups.scalar_one() == 1  # finance_team


async def test_bootstrap_admin_key(db_session: AsyncSession) -> None:
    raw_key = await bootstrap_admin_key(db_session, "my-bootstrap-secret")
    assert raw_key is not None
    assert raw_key.startswith("dlb_ak_")

    result = await db_session.execute(
        select(ApiKey).where(ApiKey.name == "bootstrap-admin")
    )
    key = result.scalar_one()
    assert "policies:write" in key.scopes


async def test_bootstrap_skips_if_admin_exists(db_session: AsyncSession) -> None:
    await bootstrap_admin_key(db_session, "secret1")
    result = await bootstrap_admin_key(db_session, "secret2")
    assert result is None  # Already has admin key, skip
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd server && uv run pytest tests/test_seeding.py -v
```

- [ ] **Step 3: Implement seeding**

Create `server/src/deliberate_server/seeding.py`:

```python
"""YAML seeding and admin key bootstrap."""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

import yaml
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from deliberate_server.auth import generate_api_key, hash_api_key
from deliberate_server.db.models import (
    ApiKey, Approver, ApproverGroup, PolicyRecord, PolicyVersion,
)

logger = logging.getLogger(__name__)

ALL_SCOPES = [
    "interrupts:write", "approvals:read", "approvals:write",
    "policies:read", "policies:write",
    "approvers:read", "approvers:write",
    "api_keys:read", "api_keys:write",
    "ledger:read", "ledger:export",
]


def _hash_definition(definition: dict) -> str:
    canonical = json.dumps(definition, sort_keys=True, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(canonical.encode()).hexdigest()}"


async def seed_from_yaml_if_empty(
    session: AsyncSession,
    policies_dir: str,
    approvers_file: str,
) -> None:
    """Seed policies and approvers from YAML if DB tables are empty."""
    # Seed policies
    policy_count = await session.execute(
        select(func.count()).select_from(PolicyRecord)
    )
    if policy_count.scalar_one() == 0:
        policies_path = Path(policies_dir)
        if policies_path.exists():
            for yaml_file in sorted(policies_path.glob("*.yaml")):
                with open(yaml_file) as f:
                    definition = yaml.safe_load(f)
                if definition is None:
                    continue
                content_hash = _hash_definition(definition)
                policy = PolicyRecord(
                    application_id="default",
                    name=definition["name"],
                    version=1,
                    definition=definition,
                    content_hash=content_hash,
                    created_by="yaml-seed",
                )
                session.add(policy)
                await session.flush()
                session.add(PolicyVersion(
                    policy_id=policy.id,
                    version=1,
                    definition=definition,
                    content_hash=content_hash,
                    changed_by="yaml-seed",
                    change_reason="Seeded from YAML",
                ))
                logger.info("Seeded policy: %s", definition["name"])

    # Seed approvers
    approver_count = await session.execute(
        select(func.count()).select_from(Approver)
    )
    if approver_count.scalar_one() == 0:
        approvers_path = Path(approvers_file)
        if approvers_path.exists():
            with open(approvers_path) as f:
                data = yaml.safe_load(f)
            for entry in data.get("approvers", []):
                session.add(Approver(
                    id=entry["id"],
                    application_id="default",
                    email=entry["email"],
                    display_name=entry.get("display_name"),
                ))
                logger.info("Seeded approver: %s", entry["id"])
            await session.flush()

            for group in data.get("groups", []):
                session.add(ApproverGroup(
                    id=group["id"],
                    application_id="default",
                    members=group["members"],
                ))
                logger.info("Seeded group: %s", group["id"])

    await session.commit()


async def bootstrap_admin_key(
    session: AsyncSession,
    bootstrap_secret: str,
) -> str | None:
    """Create an admin API key if none exists. Returns raw key or None if skipped."""
    # Check if any admin-scoped key exists
    result = await session.execute(
        select(ApiKey).where(
            ApiKey.scopes.contains(["policies:write"]),
            ApiKey.revoked_at.is_(None),
        )
    )
    if result.scalar_one_or_none() is not None:
        return None  # Admin key already exists

    raw_key, key_prefix, key_hash = generate_api_key()
    api_key = ApiKey(
        application_id="default",
        name="bootstrap-admin",
        key_prefix=key_prefix,
        key_hash=key_hash,
        scopes=ALL_SCOPES,
        created_by="bootstrap",
    )
    session.add(api_key)
    await session.commit()

    logger.warning(
        "Bootstrap admin API key created: %s (save this — it won't be shown again)",
        raw_key,
    )
    return raw_key
```

- [ ] **Step 4: Wire seeding into main.py startup**

In the lifespan function of `main.py`, after DB connection is ready:

```python
from deliberate_server.seeding import seed_from_yaml_if_empty, bootstrap_admin_key
from deliberate_server.config import get_settings

settings = get_settings()

async with async_session() as session:
    if settings.seed_from_yaml:
        await seed_from_yaml_if_empty(
            session,
            policies_dir=settings.policies_dir,
            approvers_file=settings.approvers_file,
        )

    if settings.admin_bootstrap_key:
        await bootstrap_admin_key(session, settings.admin_bootstrap_key)

    # Load policy engine and approver directory from DB
    await _policy_engine.load_from_db(session)
    await _approver_directory.load_from_db(session)
```

- [ ] **Step 5: Run tests**

```bash
cd server && uv run pytest tests/test_seeding.py -v
```

Expected: All 5 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add server/src/deliberate_server/seeding.py server/tests/test_seeding.py server/src/deliberate_server/main.py
git commit -m "feat: add YAML seeding and admin bootstrap key logic"
```

---

## Task 10: Wire Scope Checks on Existing Routes

**Files:**
- Modify: `server/src/deliberate_server/api/routes/interrupts.py`
- Modify: `server/src/deliberate_server/api/routes/approvals.py`
- Modify: `server/src/deliberate_server/api/routes/ledger.py`

- [ ] **Step 1: Add scope checks to interrupts.py**

Replace the manual `X-Deliberate-API-Key` header parsing and `Application.api_key_hash` comparison in `submit_interrupt()` with the new `require_scope("interrupts:write")` dependency:

```python
from deliberate_server.api.deps import require_scope
from deliberate_server.db.models import ApiKey

@router.post("/interrupts")
async def submit_interrupt(
    body: InterruptRequest,
    key: ApiKey = Depends(require_scope("interrupts:write")),
    session: AsyncSession = Depends(get_session),
) -> InterruptResponse:
    # Remove the old manual api_key_auth block
    # Use key.application_id instead of looking up from Application table
    ...
```

- [ ] **Step 2: Add scope checks to approvals.py**

Add to `get_approval_status`, `get_approval_payload`:

```python
from deliberate_server.api.deps import require_scope

# No auth required for decide endpoint (approvers use magic link tokens)
# But status and payload should require approvals:read

@router.get("/{approval_id}/status")
async def get_approval_status(
    approval_id: str,
    _key: ApiKey = Depends(require_scope("approvals:read")),
    ...
```

Add `?status=pending` filter support:

```python
@router.get("")
async def list_approvals(
    status: str | None = None,
    _key: ApiKey = Depends(require_scope("approvals:read")),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    query = select(Approval)
    if status:
        query = query.where(Approval.status == status)
    result = await session.execute(query)
    ...
```

- [ ] **Step 3: Add scope checks to ledger.py**

```python
from deliberate_server.api.deps import require_scope

@router.get("/ledger")
async def query_ledger(
    ...,
    _key: ApiKey = Depends(require_scope("ledger:read")),
):
    ...

@router.get("/ledger/export/json")
async def export_json(
    ...,
    _key: ApiKey = Depends(require_scope("ledger:export")),
):
    ...

@router.get("/ledger/export/csv")
async def export_csv(
    ...,
    _key: ApiKey = Depends(require_scope("ledger:export")),
):
    ...
```

- [ ] **Step 4: Run full test suite to ensure backward compatibility**

```bash
cd server && uv run pytest -v
```

Expected: All existing tests still pass (the conftest seeds a legacy API key with the correct scopes).

- [ ] **Step 5: Commit**

```bash
git add server/src/deliberate_server/api/routes/interrupts.py server/src/deliberate_server/api/routes/approvals.py server/src/deliberate_server/api/routes/ledger.py
git commit -m "feat: wire scope-based RBAC into existing API routes"
```

---

## Task 11: MCP Server Package

**Files:**
- Create: `mcp/pyproject.toml`
- Create: `mcp/src/deliberate_mcp/__init__.py`
- Create: `mcp/src/deliberate_mcp/__main__.py`
- Create: `mcp/src/deliberate_mcp/client.py`
- Create: `mcp/src/deliberate_mcp/server.py`
- Create: `mcp/tests/test_tools.py`

- [ ] **Step 1: Create package structure**

```bash
mkdir -p mcp/src/deliberate_mcp/tests
```

Create `mcp/pyproject.toml`:

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "deliberate-mcp"
version = "0.1.0"
description = "MCP server for Deliberate — AI-agent-friendly HITL approval management"
requires-python = ">=3.11"
dependencies = [
    "mcp[cli]>=1.0,<2",
    "httpx>=0.27,<1",
]

[project.scripts]
deliberate-mcp = "deliberate_mcp.__main__:main"

[tool.hatch.build.targets.wheel]
packages = ["src/deliberate_mcp"]
```

Create `mcp/src/deliberate_mcp/__init__.py`:

```python
"""Deliberate MCP Server — AI-agent-friendly HITL approval management."""
```

Create `mcp/src/deliberate_mcp/__main__.py`:

```python
"""Entry point for uvx deliberate-mcp."""
from deliberate_mcp.server import main

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Implement HTTP client wrapper**

Create `mcp/src/deliberate_mcp/client.py`:

```python
"""HTTP client for Deliberate REST API."""
from __future__ import annotations

import os
from typing import Any

import httpx


class DeliberateAPIClient:
    """Thin wrapper around Deliberate server REST API."""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> None:
        self.base_url = (base_url or os.environ.get("DELIBERATE_URL", "http://localhost:4000")).rstrip("/")
        self.api_key = api_key or os.environ.get("DELIBERATE_API_KEY", "")
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={"X-Deliberate-API-Key": self.api_key},
            timeout=30.0,
        )

    async def request(self, method: str, path: str, **kwargs: Any) -> dict | list | None:
        resp = await self._client.request(method, path, **kwargs)
        if resp.status_code == 204:
            return None
        if resp.status_code >= 400:
            detail = resp.json().get("detail", resp.text) if resp.headers.get("content-type", "").startswith("application/json") else resp.text
            return {"error": True, "status": resp.status_code, "detail": detail}
        return resp.json()

    async def get(self, path: str, **kwargs: Any) -> dict | list | None:
        return await self.request("GET", path, **kwargs)

    async def post(self, path: str, **kwargs: Any) -> dict | list | None:
        return await self.request("POST", path, **kwargs)

    async def put(self, path: str, **kwargs: Any) -> dict | list | None:
        return await self.request("PUT", path, **kwargs)

    async def delete(self, path: str, **kwargs: Any) -> dict | list | None:
        return await self.request("DELETE", path, **kwargs)
```

- [ ] **Step 3: Implement MCP server with all tools**

Create `mcp/src/deliberate_mcp/server.py`:

```python
"""Deliberate MCP Server — tool definitions for AI agents."""
from __future__ import annotations

import json
from typing import Any

from mcp.server.fastmcp import FastMCP

from deliberate_mcp.client import DeliberateAPIClient

mcp = FastMCP(
    "Deliberate",
    description="Human-in-the-loop approval management for AI agents. "
    "Create policies, manage approvers, and monitor approval workflows.",
)

_client: DeliberateAPIClient | None = None


def _get_client() -> DeliberateAPIClient:
    global _client
    if _client is None:
        _client = DeliberateAPIClient()
    return _client


# --- Policy Management ---

@mcp.tool()
async def list_policies() -> str:
    """List all registered approval policies.

    Use this to see what policies exist before creating or modifying them.
    Returns policy names, versions, and rule counts.
    """
    result = await _get_client().get("/policies")
    return json.dumps(result, indent=2)


@mcp.tool()
async def get_policy(name: str) -> str:
    """Get the full definition of a policy by name.

    Use this to inspect a policy's rules, matches, approvers, and timeouts
    before updating it.

    Args:
        name: Policy name (e.g. "refund_approval")
    """
    result = await _get_client().get(f"/policies/{name}")
    return json.dumps(result, indent=2)


@mcp.tool()
async def create_policy(
    name: str,
    matches: dict[str, Any],
    rules: list[dict[str, Any]],
) -> str:
    """Create an approval policy that routes interrupts to approvers.

    A policy defines WHEN human approval is needed and WHO should approve.

    Args:
        name: Unique policy identifier (e.g. "refund_approval")
        matches: Filter for which interrupts this policy applies to.
            - layout: Match by layout type (e.g. "financial_decision")
            - subject_contains: Match by subject text
        rules: Ordered list of rules (first match wins). Each rule:
            - name: Rule identifier
            - when: Expression (e.g. "amount.value > 1000")
            - action: "auto_approve" or "request_human"
            - approvers: {"any_of": [...]} or {"all_of": [...]}
            - timeout: Duration string (e.g. "4h", "30m")
            - notify: Channels ["email", "slack", "webhook"]
            - on_timeout: "fail" or "escalate"

    Example:
        create_policy(
            name="refund_approval",
            matches={"layout": "financial_decision"},
            rules=[
                {"name": "auto_small", "when": "amount.value < 100",
                 "action": "auto_approve", "rationale": "Small refund auto-approved"},
                {"name": "standard", "when": "amount.value >= 100",
                 "action": "request_human",
                 "approvers": {"any_of": ["finance_team"]},
                 "timeout": "4h", "notify": ["email", "slack"]}
            ]
        )
    """
    result = await _get_client().post(
        "/policies",
        json={"name": name, "matches": matches, "rules": rules},
    )
    return json.dumps(result, indent=2)


@mcp.tool()
async def update_policy(
    name: str,
    matches: dict[str, Any],
    rules: list[dict[str, Any]],
    change_reason: str | None = None,
) -> str:
    """Update an existing policy. Creates a new version.

    Args:
        name: Policy name to update
        matches: New matches filter
        rules: New ordered list of rules (replaces all existing rules)
        change_reason: Optional note explaining the change
    """
    result = await _get_client().put(
        f"/policies/{name}",
        json={"matches": matches, "rules": rules, "change_reason": change_reason},
    )
    return json.dumps(result, indent=2)


@mcp.tool()
async def delete_policy(name: str) -> str:
    """Delete a policy (soft delete).

    Args:
        name: Policy name to delete
    """
    result = await _get_client().delete(f"/policies/{name}")
    return "Policy deleted" if result is None else json.dumps(result, indent=2)


@mcp.tool()
async def test_policy(name: str, payload: dict[str, Any]) -> str:
    """Dry-run: test which rule in a policy matches a given payload.

    Use this BEFORE deploying a policy to verify it behaves as expected.

    Args:
        name: Policy name to test against
        payload: Simulated interrupt payload with fields like layout, subject, amount

    Example:
        test_policy("refund_approval", {
            "layout": "financial_decision",
            "subject": "Refund Request",
            "amount": {"value": 250, "currency": "USD"}
        })
    """
    result = await _get_client().post(f"/policies/{name}/test", json=payload)
    return json.dumps(result, indent=2)


# --- Approver Management ---

@mcp.tool()
async def list_approvers() -> str:
    """List all active approvers.

    Returns approver IDs, emails, display names, and out-of-office status.
    """
    result = await _get_client().get("/approvers")
    return json.dumps(result, indent=2)


@mcp.tool()
async def create_approver(
    id: str,
    email: str,
    display_name: str | None = None,
) -> str:
    """Add a new approver who can review and decide on approval requests.

    Args:
        id: Unique approver identifier (e.g. "finance_lead", "eng_manager")
        email: Approver's email address (used for notifications)
        display_name: Human-readable name (optional)

    Example:
        create_approver("finance_lead", "priya@example.com", "Priya Sharma")
    """
    result = await _get_client().post(
        "/approvers",
        json={"id": id, "email": email, "display_name": display_name},
    )
    return json.dumps(result, indent=2)


@mcp.tool()
async def update_approver(
    id: str,
    email: str | None = None,
    display_name: str | None = None,
    ooo_active: bool | None = None,
) -> str:
    """Update an approver's info, including out-of-office status.

    Args:
        id: Approver ID to update
        email: New email (optional)
        display_name: New display name (optional)
        ooo_active: Set to true to mark as out-of-office (optional)
    """
    body: dict[str, Any] = {}
    if email is not None:
        body["email"] = email
    if display_name is not None:
        body["display_name"] = display_name
    if ooo_active is not None:
        body["ooo_active"] = ooo_active
    result = await _get_client().put(f"/approvers/{id}", json=body)
    return json.dumps(result, indent=2)


@mcp.tool()
async def list_groups() -> str:
    """List all approver groups.

    Groups bundle multiple approvers for use in policy rules
    (e.g. any_of: ["finance_team"]).
    """
    result = await _get_client().get("/groups")
    return json.dumps(result, indent=2)


@mcp.tool()
async def create_group(
    id: str,
    members: list[str],
    display_name: str | None = None,
) -> str:
    """Create an approver group.

    Groups are referenced in policy rules for multi-approver workflows.

    Args:
        id: Unique group identifier (e.g. "finance_team")
        members: List of approver IDs who belong to this group
        display_name: Human-readable group name (optional)

    Example:
        create_group("finance_team", ["finance_lead", "cfo"], "Finance Team")
    """
    result = await _get_client().post(
        "/groups",
        json={"id": id, "members": members, "display_name": display_name},
    )
    return json.dumps(result, indent=2)


@mcp.tool()
async def update_group(
    id: str,
    members: list[str] | None = None,
    display_name: str | None = None,
) -> str:
    """Update an approver group's members or name.

    Args:
        id: Group ID to update
        members: New member list (replaces all current members)
        display_name: New display name (optional)
    """
    body: dict[str, Any] = {}
    if members is not None:
        body["members"] = members
    if display_name is not None:
        body["display_name"] = display_name
    result = await _get_client().put(f"/groups/{id}", json=body)
    return json.dumps(result, indent=2)


# --- Operations ---

@mcp.tool()
async def list_pending_approvals() -> str:
    """List all currently pending approval requests.

    Use this to see what's waiting for human review.
    """
    result = await _get_client().get("/approvals", params={"status": "pending"})
    return json.dumps(result, indent=2)


@mcp.tool()
async def get_approval_status(approval_id: str) -> str:
    """Check the status of a specific approval request.

    Args:
        approval_id: UUID of the approval to check
    """
    result = await _get_client().get(f"/approvals/{approval_id}/status")
    return json.dumps(result, indent=2)


@mcp.tool()
async def query_ledger(
    thread_id: str | None = None,
    approver_id: str | None = None,
    limit: int = 20,
) -> str:
    """Search the immutable audit log of all approval decisions.

    Args:
        thread_id: Filter by LangGraph thread ID (optional)
        approver_id: Filter by approver ID (optional)
        limit: Max entries to return (default 20)
    """
    params: dict[str, Any] = {"limit": limit}
    if thread_id:
        params["thread_id"] = thread_id
    if approver_id:
        params["approver_id"] = approver_id
    result = await _get_client().get("/ledger", params=params)
    return json.dumps(result, indent=2)


@mcp.tool()
async def list_api_keys() -> str:
    """List all active API keys (prefix only, no secrets shown).

    Use this to audit which keys exist and their scopes.
    """
    result = await _get_client().get("/api-keys")
    return json.dumps(result, indent=2)


@mcp.tool()
async def create_api_key(
    name: str,
    role: str | None = None,
    scopes: list[str] | None = None,
) -> str:
    """Create a new API key with specific permissions.

    The raw key is returned ONCE — save it immediately.

    Args:
        name: Descriptive name (e.g. "refund-agent-prod")
        role: Predefined role: "agent", "admin", "readonly", "operator"
        scopes: Explicit scope list (alternative to role). Available scopes:
            interrupts:write, approvals:read, approvals:write,
            policies:read, policies:write, approvers:read, approvers:write,
            api_keys:read, api_keys:write, ledger:read, ledger:export

    Example:
        create_api_key("refund-agent", role="agent")
    """
    body: dict[str, Any] = {"name": name}
    if role:
        body["role"] = role
    if scopes:
        body["scopes"] = scopes
    result = await _get_client().post("/api-keys", json=body)
    return json.dumps(result, indent=2)


def main() -> None:
    mcp.run(transport="stdio")
```

- [ ] **Step 4: Write basic MCP tests**

Create `mcp/tests/test_tools.py`:

```python
"""Basic tests for MCP tool definitions."""
from deliberate_mcp.server import mcp


def test_all_tools_registered() -> None:
    """Verify all 17 MCP tools are registered."""
    tool_names = {t.name for t in mcp._tool_manager.list_tools()}
    expected = {
        "list_policies", "get_policy", "create_policy", "update_policy",
        "delete_policy", "test_policy",
        "list_approvers", "create_approver", "update_approver",
        "list_groups", "create_group", "update_group",
        "list_pending_approvals", "get_approval_status", "query_ledger",
        "list_api_keys", "create_api_key",
    }
    assert expected == tool_names, f"Missing: {expected - tool_names}, Extra: {tool_names - expected}"


def test_tool_descriptions_have_examples() -> None:
    """Every tool should have a description with at least 20 chars."""
    for tool in mcp._tool_manager.list_tools():
        assert len(tool.description or "") >= 20, f"Tool {tool.name} has too short a description"
```

- [ ] **Step 5: Run MCP tests**

```bash
cd mcp && uv pip install -e "." && uv run pytest tests/ -v
```

Expected: Both tests PASS.

- [ ] **Step 6: Commit**

```bash
git add mcp/
git commit -m "feat: add deliberate-mcp standalone MCP server package"
```

---

## Task 12: llms.txt and Documentation

**Files:**
- Create: `llms.txt`
- Create: `docs/admin-api.md`
- Create: `docs/mcp.md`
- Create: `docs/rbac.md`
- Create: `docs/migration-guide.md`

- [ ] **Step 1: Create llms.txt**

Create `llms.txt` in project root:

```
# Deliberate

> Human-in-the-loop approval layer for AI agents. Agents submit approval requests, humans decide, agents resume.

## Quick Start

- Server: POST /interrupts with InterruptPayload to request human approval
- SDK: Use @approval_gate decorator on LangGraph nodes
- MCP: Install deliberate-mcp for AI coding assistant integration

## Core Concepts

- Interrupt: An agent pauses execution and requests human approval
- Policy: Rules that determine who approves and when to auto-approve (expression language: <, >, ==, !=, and, or, not, contains)
- Approver: A human who reviews and decides on interrupts (approve, modify, reject, escalate)
- Group: A set of approvers used in policy rules (any_of or all_of)
- Ledger: Immutable, hash-chained audit trail of all decisions

## Authentication

API keys with scoped permissions.
Header: X-Deliberate-API-Key: dlb_ak_...
Scopes: interrupts:write, approvals:read/write, policies:read/write, approvers:read/write, api_keys:read/write, ledger:read/export

## Admin API (Policy & Approver Management)

POST   /policies              Create policy (policies:write)
GET    /policies              List policies (policies:read)
GET    /policies/{name}       Get policy detail (policies:read)
PUT    /policies/{name}       Update policy (policies:write)
DELETE /policies/{name}       Delete policy (policies:write)
POST   /policies/{name}/test  Dry-run policy evaluation (policies:read)

POST   /approvers             Create approver (approvers:write)
GET    /approvers             List approvers (approvers:read)
PUT    /approvers/{id}        Update approver (approvers:write)

POST   /groups                Create approver group (approvers:write)
GET    /groups                List groups (approvers:read)
PUT    /groups/{id}           Update group members (approvers:write)

POST   /api-keys              Create API key (api_keys:write)
GET    /api-keys              List keys (api_keys:read)
DELETE /api-keys/{id}         Revoke key (api_keys:write)

## Agent API (Interrupt Workflow)

POST /interrupts                     Submit interrupt (interrupts:write)
GET  /approvals/{id}/status          Poll status (approvals:read)
GET  /approval-groups/{id}/status    Poll group status (approvals:read)
POST /approvals/{id}/resume-ack      Acknowledge resume (interrupts:write)

## Common Tasks

### Add HITL to a LangGraph agent
1. Create approvers: POST /approvers {id, email}
2. Create a group: POST /groups {id, members}
3. Create a policy: POST /policies {name, matches, rules}
4. Use @approval_gate(layout="...") decorator in agent code
5. Agent submits interrupt -> approver notified -> decides -> agent resumes

### Test a policy before deploying
POST /policies/{name}/test with a simulated payload to see which rule matches

## References

- OpenAPI spec: GET /openapi.json
- Swagger UI: GET /docs
- Full docs: docs/admin-api.md, docs/mcp.md, docs/rbac.md
```

- [ ] **Step 2: Create docs/admin-api.md**

Write a complete API reference document covering all CRUD endpoints with request/response examples, error codes, and scope requirements. Use the endpoint signatures from Task 5-7 as the source. Include cURL examples for each endpoint.

- [ ] **Step 3: Create docs/mcp.md**

Write MCP setup guide covering:
- Installation: `uvx deliberate-mcp` or `pip install deliberate-mcp`
- Claude Code config: JSON snippet for `.claude.json`
- Cursor config: equivalent setup
- Tool-by-tool usage examples (2-3 common workflows)
- Troubleshooting: connection errors, auth failures

- [ ] **Step 4: Create docs/rbac.md**

Write RBAC documentation covering:
- Scope list with descriptions
- Predefined roles table
- API key lifecycle (create, rotate, revoke)
- Bootstrap process (ADMIN_BOOTSTRAP_KEY)
- Security recommendations

- [ ] **Step 5: Create docs/migration-guide.md**

Write migration guide for existing users:
- What changes (DB becomes source of truth)
- What stays the same (SDK, endpoints, auth header)
- Step-by-step: run migration → first startup seeds YAML → manage via API
- Rollback instructions

- [ ] **Step 6: Commit**

```bash
git add llms.txt docs/admin-api.md docs/mcp.md docs/rbac.md docs/migration-guide.md
git commit -m "docs: add llms.txt, admin API reference, MCP guide, RBAC docs, migration guide"
```

---

## Task 13: Update Existing Documentation

**Files:**
- Modify: `README.md`
- Modify: `docs/quickstart.md`
- Modify: `docs/security.md`
- Modify: `docker-compose.yml`
- Modify: `.env.example`

- [ ] **Step 1: Update README.md**

Add an "Agent-Friendly" section after the existing Features section:

```markdown
## Agent-Friendly

Deliberate is designed for AI agents to configure and use:

- **Admin REST API** — CRUD endpoints for policies, approvers, groups, and API keys
- **MCP Server** — `uvx deliberate-mcp` for Claude Code, Cursor, and other AI coding assistants
- **Scoped RBAC** — Resource-level permissions prevent agents from modifying their own approval rules
- **llms.txt** — LLM-readable project summary at the repo root
- **OpenAPI** — Auto-generated spec at `/openapi.json`, Swagger UI at `/docs`
```

Update the architecture diagram to include Admin API and MCP.

Add MCP to the Quick Start / Installation section:

```markdown
### MCP Server (for AI coding assistants)

\`\`\`bash
# In Claude Code or Cursor config:
uvx deliberate-mcp
# Set DELIBERATE_URL and DELIBERATE_API_KEY in MCP server env
\`\`\`
```

- [ ] **Step 2: Update docs/quickstart.md**

Add "Option B: Configure via API" section showing how to create approvers, groups, and policies via cURL instead of YAML.

- [ ] **Step 3: Update docs/security.md**

Add RBAC section describing scope model, predefined roles, API key format, rotation guidance, and the admin bootstrap flow.

- [ ] **Step 4: Update docker-compose.yml**

Add new env vars to the server service:

```yaml
    environment:
      SEED_FROM_YAML: "true"
      ADMIN_BOOTSTRAP_KEY: "${ADMIN_BOOTSTRAP_KEY:-}"
```

Remove `:ro` from config volume mounts (no longer needed since YAML is only read for seeding).

- [ ] **Step 5: Commit**

```bash
git add README.md docs/quickstart.md docs/security.md docker-compose.yml .env.example
git commit -m "docs: update README, quickstart, security docs for agent-friendly features"
```

---

## Task 14: Final Integration Test

**Files:**
- Create: `server/tests/test_agent_friendly_integration.py`

- [ ] **Step 1: Write integration test**

```python
"""Integration test: full agent-friendly workflow."""
from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.anyio


async def test_full_agent_friendly_flow(client: AsyncClient, admin_api_key: str) -> None:
    """Test: create approvers -> create group -> create policy -> test policy -> submit interrupt."""
    h = {"X-Deliberate-API-Key": admin_api_key}

    # 1. Create approvers
    resp = await client.post("/approvers", headers=h, json={
        "id": "reviewer1", "email": "reviewer1@example.com",
    })
    assert resp.status_code == 201

    resp = await client.post("/approvers", headers=h, json={
        "id": "reviewer2", "email": "reviewer2@example.com",
    })
    assert resp.status_code == 201

    # 2. Create group
    resp = await client.post("/groups", headers=h, json={
        "id": "review_team", "members": ["reviewer1", "reviewer2"],
    })
    assert resp.status_code == 201

    # 3. Create policy
    resp = await client.post("/policies", headers=h, json={
        "name": "test_policy",
        "matches": {"layout": "financial_decision"},
        "rules": [
            {
                "name": "auto_tiny",
                "when": "amount.value < 10",
                "action": "auto_approve",
                "rationale": "Tiny amount",
            },
            {
                "name": "need_review",
                "when": "amount.value >= 10",
                "action": "request_human",
                "approvers": {"any_of": ["review_team"]},
                "timeout": "1h",
            },
        ],
    })
    assert resp.status_code == 201

    # 4. Test policy (dry run)
    resp = await client.post("/policies/test_policy/test", headers=h, json={
        "layout": "financial_decision",
        "subject": "Test",
        "amount": {"value": 5, "currency": "USD"},
    })
    assert resp.status_code == 200
    assert resp.json()["action"] == "auto_approve"

    resp = await client.post("/policies/test_policy/test", headers=h, json={
        "layout": "financial_decision",
        "subject": "Test",
        "amount": {"value": 500, "currency": "USD"},
    })
    assert resp.status_code == 200
    assert resp.json()["action"] == "request_human"

    # 5. Create a scoped agent key
    resp = await client.post("/api-keys", headers=h, json={
        "name": "test-agent", "role": "agent",
    })
    assert resp.status_code == 201
    agent_key = resp.json()["raw_key"]

    # 6. Verify agent key cannot modify policies
    resp = await client.post("/policies", headers={"X-Deliberate-API-Key": agent_key}, json={
        "name": "evil_policy", "matches": {}, "rules": [],
    })
    assert resp.status_code == 403

    # 7. List pending approvals (should be empty)
    resp = await client.get("/approvals", headers=h, params={"status": "pending"})
    assert resp.status_code == 200
```

- [ ] **Step 2: Run integration test**

```bash
cd server && uv run pytest tests/test_agent_friendly_integration.py -v
```

Expected: PASS.

- [ ] **Step 3: Run full test suite**

```bash
cd server && uv run pytest -v
```

Expected: ALL tests pass (existing + new).

- [ ] **Step 4: Run linting**

```bash
cd server && uv run ruff check src/ tests/ && uv run ruff format --check src/ tests/ && uv run mypy src/
```

Expected: Clean.

- [ ] **Step 5: Commit**

```bash
git add server/tests/test_agent_friendly_integration.py
git commit -m "test: add agent-friendly end-to-end integration test"
```

---

## Task 15: Final Verification

- [ ] **Step 1: Run all server tests**

```bash
cd server && uv run pytest -v --tb=short
```

- [ ] **Step 2: Run MCP tests**

```bash
cd mcp && uv run pytest tests/ -v
```

- [ ] **Step 3: Run all linting**

```bash
cd server && uv run ruff check src/ tests/ && uv run ruff format --check src/ tests/ && uv run mypy src/
```

- [ ] **Step 4: Verify docs are complete**

```bash
ls llms.txt docs/admin-api.md docs/mcp.md docs/rbac.md docs/migration-guide.md
```

All files should exist.

- [ ] **Step 5: Final commit if any fixes needed**

```bash
git status
```
