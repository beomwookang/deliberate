"""FastAPI application entry point."""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from deliberate_server.api.routes.approval_groups import router as approval_groups_router
from deliberate_server.api.routes.approvals import router as approvals_router
from deliberate_server.api.routes.auth import router as auth_router
from deliberate_server.api.routes.interrupts import router as interrupts_router
from deliberate_server.api.routes.ledger import router as ledger_router
from deliberate_server.policy import init_policy_system

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

_shutting_down = False


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    init_policy_system()
    yield
    global _shutting_down
    _shutting_down = True


app = FastAPI(
    title="Deliberate",
    description="The approval layer for LangGraph agents",
    version="0.0.1",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(interrupts_router)
app.include_router(approvals_router)
app.include_router(approval_groups_router)
app.include_router(ledger_router)


@app.get("/health")
async def health() -> dict[str, str]:
    if _shutting_down:
        return {"status": "shutting_down"}
    return {"status": "ok"}


@app.get("/metrics")
async def metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


def run() -> None:
    import uvicorn

    from deliberate_server.config import settings

    uvicorn.run(
        "deliberate_server.main:app",
        host=settings.server_host,
        port=settings.server_port,
        reload=False,
    )


if __name__ == "__main__":
    run()
