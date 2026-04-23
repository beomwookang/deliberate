"""Approver and ApproverGroup CRUD endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select

from deliberate_server.api.deps import authenticate_api_key
from deliberate_server.db.models import Approver, ApproverGroup
from deliberate_server.db.session import async_session
from deliberate_server.policy import approver_directory

approver_router = APIRouter(prefix="/approvers", tags=["approvers"])
group_router = APIRouter(prefix="/groups", tags=["approvers"])


# ---------------------------------------------------------------------------
# Approver schemas
# ---------------------------------------------------------------------------


class ApproverListItem(BaseModel):
    id: str
    email: str
    display_name: str | None
    ooo_active: bool


class ApproverDetail(BaseModel):
    id: str
    email: str
    display_name: str | None
    ooo_active: bool
    ooo_from: datetime | None
    ooo_until: datetime | None
    ooo_delegate_to: str | None
    updated_at: datetime


class ApproverCreate(BaseModel):
    id: str
    email: str
    display_name: str | None = None


class ApproverUpdate(BaseModel):
    email: str | None = None
    display_name: str | None = None
    ooo_active: bool | None = None
    ooo_from: datetime | None = None
    ooo_until: datetime | None = None
    ooo_delegate_to: str | None = None


# ---------------------------------------------------------------------------
# Group schemas
# ---------------------------------------------------------------------------


class GroupListItem(BaseModel):
    id: str
    display_name: str | None
    members: list[str]


class GroupCreate(BaseModel):
    id: str
    members: list[str]
    display_name: str | None = None


class GroupUpdate(BaseModel):
    members: list[str] | None = None
    display_name: str | None = None


# ---------------------------------------------------------------------------
# Approver endpoints
# ---------------------------------------------------------------------------


@approver_router.get("", response_model=list[ApproverListItem])
async def list_approvers(
    x_deliberate_api_key: str = Header(..., alias="X-Deliberate-API-Key"),
) -> list[ApproverListItem]:
    """List all active approvers."""
    async with async_session() as session:
        await authenticate_api_key(x_deliberate_api_key, session, required_scope="approvers:read")
        result = await session.execute(select(Approver).where(Approver.is_active.is_(True)))
        rows = result.scalars().all()
    return [
        ApproverListItem(
            id=r.id,
            email=r.email,
            display_name=r.display_name,
            ooo_active=r.ooo_active,
        )
        for r in rows
    ]


@approver_router.get("/{approver_id}", response_model=ApproverDetail)
async def get_approver(
    approver_id: str,
    x_deliberate_api_key: str = Header(..., alias="X-Deliberate-API-Key"),
) -> ApproverDetail:
    """Get approver detail by ID. 404 if not found or inactive."""
    async with async_session() as session:
        await authenticate_api_key(x_deliberate_api_key, session, required_scope="approvers:read")
        result = await session.execute(
            select(Approver).where(
                Approver.id == approver_id,
                Approver.is_active.is_(True),
            )
        )
        row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Approver '{approver_id}' not found")
    return ApproverDetail(
        id=row.id,
        email=row.email,
        display_name=row.display_name,
        ooo_active=row.ooo_active,
        ooo_from=row.ooo_from,
        ooo_until=row.ooo_until,
        ooo_delegate_to=row.ooo_delegate_to,
        updated_at=row.updated_at,
    )


@approver_router.post("", response_model=ApproverDetail, status_code=201)
async def create_approver(
    body: ApproverCreate,
    x_deliberate_api_key: str = Header(..., alias="X-Deliberate-API-Key"),
) -> ApproverDetail:
    """Create a new approver. 409 if already exists."""
    async with async_session() as session, session.begin():
        await authenticate_api_key(x_deliberate_api_key, session, required_scope="approvers:write")
        existing = await session.execute(select(Approver).where(Approver.id == body.id))
        if existing.scalar_one_or_none() is not None:
            raise HTTPException(status_code=409, detail=f"Approver '{body.id}' already exists")
        row = Approver(
            id=body.id,
            email=body.email,
            display_name=body.display_name,
        )
        session.add(row)
        await session.flush()
        await session.refresh(row)
        detail = ApproverDetail(
            id=row.id,
            email=row.email,
            display_name=row.display_name,
            ooo_active=row.ooo_active,
            ooo_from=row.ooo_from,
            ooo_until=row.ooo_until,
            ooo_delegate_to=row.ooo_delegate_to,
            updated_at=row.updated_at,
        )

    async with async_session() as session:
        await approver_directory.load_from_db(session)

    return detail


@approver_router.put("/{approver_id}", response_model=ApproverDetail)
async def update_approver(
    approver_id: str,
    body: ApproverUpdate,
    x_deliberate_api_key: str = Header(..., alias="X-Deliberate-API-Key"),
) -> ApproverDetail:
    """Update approver fields. Only updates provided fields. 404 if not found/inactive."""
    async with async_session() as session, session.begin():
        await authenticate_api_key(x_deliberate_api_key, session, required_scope="approvers:write")
        result = await session.execute(
            select(Approver).where(
                Approver.id == approver_id,
                Approver.is_active.is_(True),
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Approver '{approver_id}' not found")
        if body.email is not None:
            row.email = body.email
        if body.display_name is not None:
            row.display_name = body.display_name
        if body.ooo_active is not None:
            row.ooo_active = body.ooo_active
        if body.ooo_from is not None:
            row.ooo_from = body.ooo_from
        if body.ooo_until is not None:
            row.ooo_until = body.ooo_until
        if body.ooo_delegate_to is not None:
            row.ooo_delegate_to = body.ooo_delegate_to
        row.updated_at = func.now()
        await session.flush()
        await session.refresh(row)
        detail = ApproverDetail(
            id=row.id,
            email=row.email,
            display_name=row.display_name,
            ooo_active=row.ooo_active,
            ooo_from=row.ooo_from,
            ooo_until=row.ooo_until,
            ooo_delegate_to=row.ooo_delegate_to,
            updated_at=row.updated_at,
        )

    async with async_session() as session:
        await approver_directory.load_from_db(session)

    return detail


@approver_router.delete("/{approver_id}", status_code=204)
async def delete_approver(
    approver_id: str,
    x_deliberate_api_key: str = Header(..., alias="X-Deliberate-API-Key"),
) -> None:
    """Soft-delete an approver. 404 if not found/inactive."""
    async with async_session() as session, session.begin():
        await authenticate_api_key(x_deliberate_api_key, session, required_scope="approvers:write")
        result = await session.execute(
            select(Approver).where(
                Approver.id == approver_id,
                Approver.is_active.is_(True),
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Approver '{approver_id}' not found")
        row.is_active = False
        row.updated_at = func.now()

    async with async_session() as session:
        await approver_directory.load_from_db(session)


# ---------------------------------------------------------------------------
# Group endpoints
# ---------------------------------------------------------------------------


async def _validate_members(session: Any, member_ids: list[str]) -> list[str]:
    """Return list of invalid member IDs (not found as active approvers)."""
    if not member_ids:
        return []
    result = await session.execute(
        select(Approver.id).where(
            Approver.id.in_(member_ids),
            Approver.is_active.is_(True),
        )
    )
    found = {row[0] for row in result.fetchall()}
    return [m for m in member_ids if m not in found]


@group_router.get("", response_model=list[GroupListItem])
async def list_groups(
    x_deliberate_api_key: str = Header(..., alias="X-Deliberate-API-Key"),
) -> list[GroupListItem]:
    """List all active approver groups."""
    async with async_session() as session:
        await authenticate_api_key(x_deliberate_api_key, session, required_scope="approvers:read")
        result = await session.execute(
            select(ApproverGroup).where(ApproverGroup.is_active.is_(True))
        )
        rows = result.scalars().all()
    return [GroupListItem(id=r.id, display_name=r.display_name, members=r.members) for r in rows]


@group_router.post("", response_model=GroupListItem, status_code=201)
async def create_group(
    body: GroupCreate,
    x_deliberate_api_key: str = Header(..., alias="X-Deliberate-API-Key"),
) -> GroupListItem:
    """Create a new approver group. Validates all member IDs. 201 on success."""
    async with async_session() as session, session.begin():
        await authenticate_api_key(x_deliberate_api_key, session, required_scope="approvers:write")
        existing = await session.execute(select(ApproverGroup).where(ApproverGroup.id == body.id))
        if existing.scalar_one_or_none() is not None:
            raise HTTPException(status_code=409, detail=f"Group '{body.id}' already exists")
        invalid = await _validate_members(session, body.members)
        if invalid:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid member IDs (not found as active approvers): {invalid}",
            )
        row = ApproverGroup(
            id=body.id,
            display_name=body.display_name,
            members=body.members,
        )
        session.add(row)
        await session.flush()
        await session.refresh(row)
        item = GroupListItem(id=row.id, display_name=row.display_name, members=row.members)

    async with async_session() as session:
        await approver_directory.load_from_db(session)

    return item


@group_router.put("/{group_id}", response_model=GroupListItem)
async def update_group(
    group_id: str,
    body: GroupUpdate,
    x_deliberate_api_key: str = Header(..., alias="X-Deliberate-API-Key"),
) -> GroupListItem:
    """Update group fields. Validates members if provided. 404 if not found/inactive."""
    async with async_session() as session, session.begin():
        await authenticate_api_key(x_deliberate_api_key, session, required_scope="approvers:write")
        result = await session.execute(
            select(ApproverGroup).where(
                ApproverGroup.id == group_id,
                ApproverGroup.is_active.is_(True),
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Group '{group_id}' not found")
        if body.members is not None:
            invalid = await _validate_members(session, body.members)
            if invalid:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid member IDs (not found as active approvers): {invalid}",
                )
            row.members = body.members
        if body.display_name is not None:
            row.display_name = body.display_name
        row.updated_at = func.now()
        await session.flush()
        await session.refresh(row)
        item = GroupListItem(id=row.id, display_name=row.display_name, members=row.members)

    async with async_session() as session:
        await approver_directory.load_from_db(session)

    return item


@group_router.delete("/{group_id}", status_code=204)
async def delete_group(
    group_id: str,
    x_deliberate_api_key: str = Header(..., alias="X-Deliberate-API-Key"),
) -> None:
    """Soft-delete an approver group. 404 if not found/inactive."""
    async with async_session() as session, session.begin():
        await authenticate_api_key(x_deliberate_api_key, session, required_scope="approvers:write")
        result = await session.execute(
            select(ApproverGroup).where(
                ApproverGroup.id == group_id,
                ApproverGroup.is_active.is_(True),
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Group '{group_id}' not found")
        row.is_active = False
        row.updated_at = func.now()

    async with async_session() as session:
        await approver_directory.load_from_db(session)
