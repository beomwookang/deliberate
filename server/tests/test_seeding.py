"""Tests for YAML seeding and admin bootstrap logic."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-tests")
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://deliberate:deliberate@localhost:5432/deliberate"
)

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from deliberate_server.config import settings
from deliberate_server.db.models import ApiKey, Approver, ApproverGroup, Base, PolicyRecord
from deliberate_server.seeding import bootstrap_admin_key, seed_from_yaml_if_empty

pytestmark = pytest.mark.anyio

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_POLICIES_DIR = str(_PROJECT_ROOT / "examples" / "policies")
_APPROVERS_FILE = str(_PROJECT_ROOT / "config" / "approvers.yaml")


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:  # type: ignore[misc]
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
        await conn.run_sync(Base.metadata.create_all)

    # Seed the default application (required for FK)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO applications (id, display_name, api_key_hash)"
                " VALUES ('default', 'Default', 'unused')"
            )
        )

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


async def test_seed_policies_when_empty(db_session: AsyncSession) -> None:
    """Seeds 2 policies from examples/policies/ when table is empty."""
    await seed_from_yaml_if_empty(db_session, _POLICIES_DIR, _APPROVERS_FILE)

    result = await db_session.execute(select(func.count()).select_from(PolicyRecord))
    count = result.scalar_one()
    assert count == 2, f"Expected 2 policies, got {count}"


async def test_seed_does_not_overwrite(db_session: AsyncSession) -> None:
    """Does not overwrite policies if at least one already exists."""
    # Insert one policy manually
    existing = PolicyRecord(
        id=uuid.uuid4(),
        name="pre_existing",
        version=1,
        definition={"name": "pre_existing"},
        content_hash="sha256:abc",
        created_by="test",
        is_active=True,
    )
    db_session.add(existing)
    await db_session.commit()

    await seed_from_yaml_if_empty(db_session, _POLICIES_DIR, _APPROVERS_FILE)

    result = await db_session.execute(select(func.count()).select_from(PolicyRecord))
    count = result.scalar_one()
    assert count == 1, f"Expected 1 policy (no overwrite), got {count}"


async def test_seed_approvers(db_session: AsyncSession) -> None:
    """Seeds 2 approvers and 1 group from config/approvers.yaml."""
    await seed_from_yaml_if_empty(db_session, _POLICIES_DIR, _APPROVERS_FILE)

    approver_result = await db_session.execute(select(func.count()).select_from(Approver))
    approver_count = approver_result.scalar_one()
    assert approver_count == 2, f"Expected 2 approvers, got {approver_count}"

    group_result = await db_session.execute(select(func.count()).select_from(ApproverGroup))
    group_count = group_result.scalar_one()
    assert group_count == 1, f"Expected 1 group, got {group_count}"


async def test_bootstrap_admin_key(db_session: AsyncSession) -> None:
    """Creates admin key when none exists; returns raw key starting with dlb_ak_."""
    raw_key = await bootstrap_admin_key(db_session, "test-bootstrap-secret")

    assert raw_key is not None
    assert raw_key.startswith("dlb_ak_"), f"Expected key to start with dlb_ak_, got {raw_key!r}"

    result = await db_session.execute(select(func.count()).select_from(ApiKey))
    count = result.scalar_one()
    assert count == 1, f"Expected 1 API key row, got {count}"


async def test_bootstrap_skips_if_admin_exists(db_session: AsyncSession) -> None:
    """Second bootstrap call returns None when admin key already exists."""
    first = await bootstrap_admin_key(db_session, "test-bootstrap-secret")
    assert first is not None

    second = await bootstrap_admin_key(db_session, "test-bootstrap-secret")
    assert second is None

    result = await db_session.execute(select(func.count()).select_from(ApiKey))
    count = result.scalar_one()
    assert count == 1, f"Expected still 1 API key row, got {count}"
