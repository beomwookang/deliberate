"""Interrupt submission endpoint (PRD §6.2, §6.4 step 2)."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from deliberate.types import InterruptPayload
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from deliberate_server.auth import verify_api_key
from deliberate_server.config import settings
from deliberate_server.db.models import Application, Approval, Interrupt
from deliberate_server.db.session import async_session

logger = logging.getLogger("deliberate_server.api.interrupts")

router = APIRouter(prefix="/interrupts", tags=["interrupts"])

M1_TIMEOUT_HOURS = 1


class InterruptRequest(BaseModel):
    """Request body for POST /interrupts."""

    thread_id: str
    trace_id: str | None = None
    payload: dict[str, Any]


class InterruptResponse(BaseModel):
    """Response body for POST /interrupts."""

    approval_id: str
    status: str


@router.post("", response_model=InterruptResponse)
async def submit_interrupt(
    body: InterruptRequest,
    x_deliberate_api_key: str = Header(..., alias="X-Deliberate-API-Key"),
) -> InterruptResponse:
    """Submit a new interrupt from the SDK.

    Authenticates via API key, validates payload, creates interrupt + approval rows,
    and logs the approval URL.
    """
    # Authenticate: look up application by hashed API key
    async with async_session() as session:
        result = await session.execute(select(Application))
        applications = result.scalars().all()

    app_row: Application | None = None
    for app in applications:
        if verify_api_key(x_deliberate_api_key, app.api_key_hash):
            app_row = app
            break

    if app_row is None:
        raise HTTPException(status_code=401, detail="Invalid API key")

    # Validate the payload against InterruptPayload schema
    try:
        validated_payload = InterruptPayload(**body.payload)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Invalid interrupt payload: {e}") from e

    # Resolve approver: M1 uses env var, no policy engine
    approver_email = settings.default_approver_email
    approver_id = approver_email or None

    # Create interrupt + approval transactionally
    interrupt_id = uuid.uuid4()
    approval_id = uuid.uuid4()
    now = datetime.now(UTC)

    async with async_session() as session, session.begin():
        interrupt_row = Interrupt(
            id=interrupt_id,
            application_id=app_row.id,
            thread_id=body.thread_id,
            trace_id=body.trace_id,
            layout=validated_payload.layout,
            payload=body.payload,
            policy_name=None,
            received_at=now,
        )
        session.add(interrupt_row)
        await session.flush()

        approval_row = Approval(
            id=approval_id,
            interrupt_id=interrupt_id,
            approver_id=approver_id,
            acting_for=None,
            status="pending",
            timeout_at=now + timedelta(hours=M1_TIMEOUT_HOURS),
            escalated_to=None,
            delegation_reason=None,
            created_at=now,
        )
        session.add(approval_row)

    # Log the approval URL with grep-friendly prefix
    approval_url = f"{settings.ui_url}/a/{approval_id}"
    logger.info("[APPROVAL_URL] %s", approval_url)

    return InterruptResponse(approval_id=str(approval_id), status="pending")
