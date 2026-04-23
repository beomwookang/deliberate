"""Auth dependencies for scope-based RBAC.

The existing codebase uses ``async with async_session() as session`` inside each
route handler (no shared FastAPI Depends-based session).  With NullPool (tests),
only one connection exists at a time, so auth and route logic must share the same
session.  This module provides ``authenticate_api_key`` — a plain async helper
that route handlers call at the top of their own session block.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from deliberate_server.auth import hash_api_key
from deliberate_server.db.models import ApiKey


async def authenticate_api_key(
    raw_key: str,
    session: AsyncSession,
    *,
    required_scope: str | None = None,
) -> ApiKey:
    """Validate an API key and optionally check scope.

    Call this at the start of a route handler, inside the handler's own
    ``async with async_session() as session`` block.

    Raises:
        HTTPException 401 – invalid, revoked, or expired key
        HTTPException 403 – key lacks the required scope
    """
    key_hash = hash_api_key(raw_key)
    result = await session.execute(
        select(ApiKey).where(
            ApiKey.key_hash == key_hash,
            ApiKey.revoked_at.is_(None),
        )
    )
    api_key = result.scalar_one_or_none()
    if api_key is None:
        raise HTTPException(status_code=401, detail="Invalid or revoked API key")

    if api_key.expires_at and api_key.expires_at < datetime.now(UTC):
        raise HTTPException(status_code=401, detail="API key has expired")

    if required_scope and required_scope not in api_key.scopes:
        raise HTTPException(
            status_code=403,
            detail=f"API key missing required scope: {required_scope}",
        )

    # Update last_used_at (best-effort, inside caller's transaction)
    await session.execute(
        update(ApiKey).where(ApiKey.id == api_key.id).values(last_used_at=datetime.now(UTC))
    )

    return api_key
