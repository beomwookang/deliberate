"""API key management endpoints."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from deliberate_server.api.deps import authenticate_api_key
from deliberate_server.auth import generate_api_key
from deliberate_server.db.models import ApiKey
from deliberate_server.db.session import async_session

router = APIRouter(prefix="/api-keys", tags=["api-keys"])

ALL_SCOPES = [
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
]

ROLE_SCOPES: dict[str, list[str]] = {
    "agent": ["interrupts:write", "approvals:read"],
    "admin": ALL_SCOPES,
    "readonly": ["policies:read", "approvers:read", "ledger:read"],
    "operator": ["approvers:read", "approvers:write", "policies:read", "api_keys:read"],
}


class ApiKeyResponse(BaseModel):
    id: str
    name: str
    key_prefix: str
    scopes: list[str]
    created_by: str
    created_at: str
    last_used_at: str | None


class CreateApiKeyRequest(BaseModel):
    name: str
    scopes: list[str] | None = None
    role: str | None = None


class CreateApiKeyResponse(BaseModel):
    id: str
    name: str
    key_prefix: str
    raw_key: str
    scopes: list[str]


@router.get("", response_model=list[ApiKeyResponse])
async def list_api_keys(
    x_deliberate_api_key: str = Header(..., alias="X-Deliberate-API-Key"),
) -> list[ApiKeyResponse]:
    """List all active (non-revoked) API keys. Never exposes raw_key or key_hash."""
    async with async_session() as session:
        await authenticate_api_key(x_deliberate_api_key, session, required_scope="api_keys:read")
        result = await session.execute(
            select(ApiKey).where(ApiKey.revoked_at.is_(None)).order_by(ApiKey.created_at.desc())
        )
        keys = result.scalars().all()
        return [
            ApiKeyResponse(
                id=str(key.id),
                name=key.name,
                key_prefix=key.key_prefix,
                scopes=key.scopes,
                created_by=key.created_by,
                created_at=key.created_at.isoformat(),
                last_used_at=key.last_used_at.isoformat() if key.last_used_at else None,
            )
            for key in keys
        ]


@router.post("", response_model=CreateApiKeyResponse, status_code=201)
async def create_api_key(
    body: CreateApiKeyRequest,
    x_deliberate_api_key: str = Header(..., alias="X-Deliberate-API-Key"),
) -> CreateApiKeyResponse:
    """Create a new API key. raw_key is returned once only."""
    if body.role is not None:
        if body.role not in ROLE_SCOPES:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown role '{body.role}'. Valid roles: {list(ROLE_SCOPES)}",
            )
        scopes = ROLE_SCOPES[body.role]
    elif body.scopes is not None:
        invalid = [s for s in body.scopes if s not in ALL_SCOPES]
        if invalid:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid scopes: {invalid}. Valid scopes: {ALL_SCOPES}",
            )
        scopes = body.scopes
    else:
        raise HTTPException(
            status_code=400,
            detail="Either 'role' or 'scopes' must be provided.",
        )

    raw_key, key_prefix, key_hash = generate_api_key()

    async with async_session() as session, session.begin():
        caller = await authenticate_api_key(
            x_deliberate_api_key, session, required_scope="api_keys:write"
        )
        new_key = ApiKey(
            id=uuid.uuid4(),
            name=body.name,
            key_prefix=key_prefix,
            key_hash=key_hash,
            scopes=scopes,
            created_by=str(caller.id),
            created_at=datetime.now(UTC),
        )
        session.add(new_key)

    return CreateApiKeyResponse(
        id=str(new_key.id),
        name=new_key.name,
        key_prefix=new_key.key_prefix,
        raw_key=raw_key,
        scopes=scopes,
    )


@router.delete("/{key_id}", status_code=204)
async def revoke_api_key(
    key_id: uuid.UUID,
    x_deliberate_api_key: str = Header(..., alias="X-Deliberate-API-Key"),
) -> None:
    """Revoke an API key by setting revoked_at. Returns 404 if not found."""
    async with async_session() as session, session.begin():
        await authenticate_api_key(x_deliberate_api_key, session, required_scope="api_keys:write")
        result = await session.execute(select(ApiKey).where(ApiKey.id == key_id))
        key = result.scalar_one_or_none()
        if key is None:
            raise HTTPException(status_code=404, detail="API key not found")
        key.revoked_at = datetime.now(UTC)
