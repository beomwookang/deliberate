"""Ledger query and export endpoints — stub for M3."""

from fastapi import APIRouter

router = APIRouter(prefix="/ledger", tags=["ledger"])

# GET /ledger/ — query ledger entries (PRD §6.2)
# GET /ledger/export — JSON/CSV export (PRD §6.2)
