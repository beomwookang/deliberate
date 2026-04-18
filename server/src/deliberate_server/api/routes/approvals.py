"""Approval endpoints — stub for M1."""

from fastapi import APIRouter

router = APIRouter(prefix="/approvals", tags=["approvals"])

# GET /approvals/{token} — approver opens the approval page (PRD §6.2)
# POST /approvals/{id}/decide — approver submits decision (PRD §6.2)
# GET /approvals/{id}/status — SDK polls for decision (PRD §6.4)
