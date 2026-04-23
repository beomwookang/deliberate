"""Ledger query endpoint (PRD §6.2)."""

from __future__ import annotations

import base64
import csv
import io
import json
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Header, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select, text

from deliberate_server.api.deps import authenticate_api_key
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


class LedgerQueryResponse(BaseModel):
    entries: list[LedgerEntryResponse]
    next_cursor: str | None = None
    total_hint: int | None = None  # Approximate count when available


@router.get("", response_model=LedgerQueryResponse)
async def query_ledger(
    x_deliberate_api_key: str = Header(..., alias="X-Deliberate-API-Key"),
    thread_id: str | None = Query(None, description="Filter by LangGraph thread ID"),
    approver_id: str | None = Query(None, description="Filter by approver ID"),
    date_from: datetime | None = Query(None, description="Filter from date (inclusive)"),  # noqa: B008
    date_to: datetime | None = Query(None, description="Filter until date (inclusive)"),  # noqa: B008
    q: str | None = Query(None, description="Full-text search in rationale notes"),
    cursor: str | None = Query(None, description="Cursor for pagination (base64-encoded)"),
    limit: int = Query(50, ge=1, le=500),
) -> LedgerQueryResponse:
    """Query ledger entries with filters and cursor-based pagination."""
    async with async_session() as session:
        await authenticate_api_key(x_deliberate_api_key, session, required_scope="ledger:read")
        stmt = select(LedgerEntry).order_by(LedgerEntry.created_at.desc(), LedgerEntry.id.desc())

        # Apply filters
        if thread_id:
            stmt = stmt.where(text("content->>'thread_id' = :tid").bindparams(tid=thread_id))

        if approver_id:
            stmt = stmt.where(
                text("content->'approval'->>'approver_id' = :aid").bindparams(aid=approver_id)
            )

        if date_from:
            stmt = stmt.where(LedgerEntry.created_at >= date_from)

        if date_to:
            stmt = stmt.where(LedgerEntry.created_at <= date_to)

        if q:
            stmt = stmt.where(
                text("content->'approval'->>'rationale_notes' ILIKE :q").bindparams(q=f"%{q}%")
            )

        # Apply cursor
        if cursor:
            try:
                decoded = base64.b64decode(cursor).decode()
                cursor_data = json.loads(decoded)
                cursor_ts = cursor_data["ts"]
                cursor_id = cursor_data["id"]
                # For descending order: entries before cursor
                stmt = stmt.where(
                    text("(created_at, id) < (:cts::timestamptz, :cid::uuid)").bindparams(
                        cts=cursor_ts, cid=cursor_id
                    )
                )
            except Exception:
                pass  # Invalid cursor — ignore

        # Fetch limit + 1 to check for next page
        stmt = stmt.limit(limit + 1)

        result = await session.execute(stmt)
        entries = list(result.scalars().all())

        has_next = len(entries) > limit
        if has_next:
            entries = entries[:limit]

        # Build next_cursor
        next_cursor: str | None = None
        if has_next and entries:
            last = entries[-1]
            cursor_payload = {
                "ts": last.created_at.isoformat() if last.created_at else "",
                "id": str(last.id),
            }
            next_cursor = base64.b64encode(json.dumps(cursor_payload).encode()).decode()

        return LedgerQueryResponse(
            entries=[
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
            ],
            next_cursor=next_cursor,
        )


@router.get("/export/json")
async def export_ledger_json(
    x_deliberate_api_key: str = Header(..., alias="X-Deliberate-API-Key"),
    thread_id: str | None = Query(None),
    approver_id: str | None = Query(None),
    date_from: datetime | None = Query(None),  # noqa: B008
    date_to: datetime | None = Query(None),  # noqa: B008
    q: str | None = Query(None),
) -> StreamingResponse:
    """Export ledger entries as JSON file."""
    async with async_session() as session:
        await authenticate_api_key(x_deliberate_api_key, session, required_scope="ledger:export")
        stmt = select(LedgerEntry).order_by(LedgerEntry.created_at.desc())

        if thread_id:
            stmt = stmt.where(text("content->>'thread_id' = :tid").bindparams(tid=thread_id))
        if approver_id:
            stmt = stmt.where(
                text("content->'approval'->>'approver_id' = :aid").bindparams(aid=approver_id)
            )
        if date_from:
            stmt = stmt.where(LedgerEntry.created_at >= date_from)
        if date_to:
            stmt = stmt.where(LedgerEntry.created_at <= date_to)
        if q:
            stmt = stmt.where(
                text("content->'approval'->>'rationale_notes' ILIKE :q").bindparams(q=f"%{q}%")
            )

        result = await session.execute(stmt)
        entries = result.scalars().all()

        data = [e.content for e in entries]

    content = json.dumps(data, indent=2, default=str)

    return StreamingResponse(
        iter([content]),
        media_type="application/json",
        headers={
            "Content-Disposition": "attachment; filename=ledger_export.json",
        },
    )


@router.get("/export/csv")
async def export_ledger_csv(
    x_deliberate_api_key: str = Header(..., alias="X-Deliberate-API-Key"),
    thread_id: str | None = Query(None),
    approver_id: str | None = Query(None),
    date_from: datetime | None = Query(None),  # noqa: B008
    date_to: datetime | None = Query(None),  # noqa: B008
    q: str | None = Query(None),
) -> StreamingResponse:
    """Export ledger entries as CSV file."""
    async with async_session() as session:
        await authenticate_api_key(x_deliberate_api_key, session, required_scope="ledger:export")
        stmt = select(LedgerEntry).order_by(LedgerEntry.created_at.desc())

        if thread_id:
            stmt = stmt.where(text("content->>'thread_id' = :tid").bindparams(tid=thread_id))
        if approver_id:
            stmt = stmt.where(
                text("content->'approval'->>'approver_id' = :aid").bindparams(aid=approver_id)
            )
        if date_from:
            stmt = stmt.where(LedgerEntry.created_at >= date_from)
        if date_to:
            stmt = stmt.where(LedgerEntry.created_at <= date_to)
        if q:
            stmt = stmt.where(
                text("content->'approval'->>'rationale_notes' ILIKE :q").bindparams(q=f"%{q}%")
            )

        result = await session.execute(stmt)
        entries = result.scalars().all()

    output = io.StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_ALL)

    writer.writerow(
        [
            "id",
            "thread_id",
            "decision_type",
            "approver_email",
            "decided_at",
            "rationale_category",
            "resume_status",
        ]
    )

    for entry in entries:
        entry_content = entry.content
        approval = entry_content.get("approval", {})
        writer.writerow(
            [
                entry_content.get("id", ""),
                entry_content.get("thread_id", ""),
                approval.get("decision_type", ""),
                approval.get("approver_email", ""),
                approval.get("decided_at", ""),
                approval.get("rationale_category", ""),
                entry.resume_status,
            ]
        )

    csv_content = output.getvalue()

    return StreamingResponse(
        iter([csv_content]),
        media_type="text/csv",
        headers={
            "Content-Disposition": "attachment; filename=ledger_export.csv",
        },
    )
