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

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from deliberate_server.auth import hash_api_key
from deliberate_server.config import settings
from deliberate_server.db.models import Base

_TEST_DB_URL = settings.database_url


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """Async test client with a fresh NullPool engine per test.

    Creates tables if needed, cleans data, seeds default application.
    """
    engine = create_async_engine(_TEST_DB_URL, poolclass=NullPool)

    # Create tables + clean + seed in one connection sequence
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with engine.begin() as conn:
        for tbl in ("notification_attempts", "ledger_entries", "decisions", "approvals", "interrupts", "approvers"):
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
