"""Interrupt submission endpoint — stub for M1."""

from fastapi import APIRouter

router = APIRouter(prefix="/interrupts", tags=["interrupts"])

# POST /interrupts — agent submits a new interrupt (PRD §6.2)
