"""Tests for scope-based RBAC via authenticate_api_key."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from deliberate_server.api.deps import authenticate_api_key
from deliberate_server.auth import hash_api_key
from deliberate_server.db.models import ApiKey

pytestmark = pytest.mark.anyio


def _make_api_key(scopes: list[str], revoked: bool = False, expired: bool = False) -> ApiKey:
    """Create an ApiKey instance for testing (uses normal constructor)."""
    return ApiKey(
        application_id="default",
        name="test",
        key_prefix="dlb_ak_test1234",
        key_hash=hash_api_key("test-key"),
        scopes=scopes,
        created_by="test",
        revoked_at=datetime.now(UTC) if revoked else None,
        expires_at=(datetime.now(UTC) - timedelta(hours=1)) if expired else None,
    )


def _mock_session(return_value: ApiKey | None) -> AsyncMock:
    """Return a mock AsyncSession whose execute() yields scalar_one_or_none."""
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = return_value
    mock_session.execute.return_value = mock_result
    return mock_session


async def test_valid_key_passes() -> None:
    """Valid key with correct scope is returned."""
    api_key = _make_api_key(scopes=["policies:read"])
    result = await authenticate_api_key(
        "test-key", _mock_session(api_key), required_scope="policies:read"
    )
    assert result.scopes == ["policies:read"]


async def test_invalid_key_returns_401() -> None:
    """Unknown key returns 401."""
    with pytest.raises(HTTPException) as exc_info:
        await authenticate_api_key("bad-key", _mock_session(None))
    assert exc_info.value.status_code == 401


async def test_expired_key_returns_401() -> None:
    """Expired key returns 401."""
    api_key = _make_api_key(scopes=["policies:read"], expired=True)
    with pytest.raises(HTTPException) as exc_info:
        await authenticate_api_key("test-key", _mock_session(api_key))
    assert exc_info.value.status_code == 401


async def test_correct_scope_passes() -> None:
    """Key with required scope passes."""
    api_key = _make_api_key(scopes=["policies:read", "policies:write"])
    result = await authenticate_api_key(
        "test-key", _mock_session(api_key), required_scope="policies:read"
    )
    assert result == api_key


async def test_missing_scope_returns_403() -> None:
    """Key without required scope returns 403."""
    api_key = _make_api_key(scopes=["policies:read"])
    with pytest.raises(HTTPException) as exc_info:
        await authenticate_api_key(
            "test-key", _mock_session(api_key), required_scope="policies:write"
        )
    assert exc_info.value.status_code == 403
    assert "policies:write" in exc_info.value.detail
