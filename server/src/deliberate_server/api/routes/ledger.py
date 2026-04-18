"""Ledger query endpoint (PRD §6.2)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import select, text

from deliberate_server.db.models import LedgerEntry
from deliberate_server.db.session import async_session

router = APIRouter(prefix="/ledger", tags=["ledger"])


class LedgerEntryResponse(BaseModel):
    id: str
    application_id: str
    interrupt_id: str
    decision_id: str | None
    resume_status: str
    resume_latency_ms: int | None
    content: dict[str, Any]
    content_hash: str
    created_at: str


@router.get("", response_model=list[LedgerEntryResponse])
async def query_ledger(
    thread_id: str | None = Query(None, description="Filter by LangGraph thread ID"),
    limit: int = Query(50, ge=1, le=500),
) -> list[LedgerEntryResponse]:
    """Query ledger entries, optionally filtered by thread_id."""
    async with async_session() as session:
        stmt = select(LedgerEntry).order_by(LedgerEntry.created_at.desc()).limit(limit)

        if thread_id:
            stmt = stmt.where(text("content->>'thread_id' = :tid").bindparams(tid=thread_id))

        result = await session.execute(stmt)
        entries = result.scalars().all()

        return [
            LedgerEntryResponse(
                id=str(e.id),
                application_id=e.application_id,
                interrupt_id=str(e.interrupt_id),
                decision_id=str(e.decision_id) if e.decision_id else None,
                resume_status=e.resume_status,
                resume_latency_ms=e.resume_latency_ms,
                content=e.content,
                content_hash=e.content_hash,
                created_at=e.created_at.isoformat() if e.created_at else "",
            )
            for e in entries
        ]
