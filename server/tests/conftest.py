"""Shared fixtures for server tests.

Tests run against a real Postgres database (docker compose up -d postgres).
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator

# Set env vars BEFORE importing any server code
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-tests")
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

from deliberate_server.auth import generate_api_key, hash_api_key
from deliberate_server.config import settings
from deliberate_server.db.models import Base

_TEST_DB_URL = settings.database_url

_test_keys: dict[str, str] = {}


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """Async test client with a fresh NullPool engine per test.

    Creates tables if needed, cleans data, seeds default application.
    """
    engine = create_async_engine(_TEST_DB_URL, poolclass=NullPool)

    # Drop and recreate tables to pick up schema changes (new columns).
    # Use CASCADE to handle any stale FK dependencies not tracked in models.
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
        await conn.run_sync(Base.metadata.create_all)

    async with engine.begin() as conn:
        tables = (
            "notification_attempts",
            "ledger_entries",
            "decisions",
            "approvals",
            "interrupts",
            "approvers",
        )
        for tbl in tables:
            await conn.execute(text(f"DELETE FROM {tbl}"))
        await conn.execute(text("DELETE FROM applications"))
        key_hash = hash_api_key("test-api-key")
        await conn.execute(
            text(
                "INSERT INTO applications (id, display_name, api_key_hash) "
                "VALUES (:id, :name, :hash)"
            ),
            {"id": "default", "name": "Default Application", "hash": key_hash},
        )

    # Seed API keys via raw SQL (consistent with application seed above)
    _admin_raw, _admin_prefix, _admin_hash = generate_api_key()
    _agent_raw, _agent_prefix, _agent_hash = generate_api_key()
    _legacy_hash = hash_api_key("test-api-key")

    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO api_keys "
                "(id, application_id, name, key_prefix, key_hash, scopes, created_by) "
                "VALUES (gen_random_uuid(), :app, :name, :prefix, :hash, :scopes, :by)"
            ),
            {
                "app": "default",
                "name": "test-admin",
                "prefix": _admin_prefix,
                "hash": _admin_hash,
                "scopes": [
                    "interrupts:write",
                    "approvals:read",
                    "approvals:write",
                    "policies:read",
                    "policies:write",
                    "approvers:read",
                    "approvers:write",
                    "api_keys:read",
                    "api_keys:write",
                    "ledger:read",
                    "ledger:export",
                ],
                "by": "test",
            },
        )
        await conn.execute(
            text(
                "INSERT INTO api_keys "
                "(id, application_id, name, key_prefix, key_hash, scopes, created_by) "
                "VALUES (gen_random_uuid(), :app, :name, :prefix, :hash, :scopes, :by)"
            ),
            {
                "app": "default",
                "name": "test-agent",
                "prefix": _agent_prefix,
                "hash": _agent_hash,
                "scopes": ["interrupts:write", "approvals:read"],
                "by": "test",
            },
        )
        await conn.execute(
            text(
                "INSERT INTO api_keys "
                "(id, application_id, name, key_prefix, key_hash, scopes, created_by) "
                "VALUES (gen_random_uuid(), :app, :name, :prefix, :hash, :scopes, :by)"
            ),
            {
                "app": "default",
                "name": "legacy-test",
                "prefix": "test-api-key-"[:16],
                "hash": _legacy_hash,
                "scopes": ["interrupts:write", "approvals:read", "approvals:write", "ledger:read"],
                "by": "test",
            },
        )

    _test_keys["admin"] = _admin_raw
    _test_keys["agent"] = _agent_raw

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # Patch the app's session factory
    import deliberate_server.db.session as session_module

    original = session_module.async_session
    session_module.async_session = factory

    from deliberate_server.main import app

    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    session_module.async_session = original
    await engine.dispose()


@pytest.fixture
def admin_api_key() -> str:
    return _test_keys["admin"]


@pytest.fixture
def agent_api_key() -> str:
    return _test_keys["agent"]
