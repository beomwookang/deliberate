"""FastAPI application entry point."""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from deliberate_server.api.routes.approvals import router as approvals_router
from deliberate_server.api.routes.interrupts import router as interrupts_router
from deliberate_server.api.routes.ledger import router as ledger_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

app = FastAPI(
    title="Deliberate",
    description="The approval layer for LangGraph agents",
    version="0.0.1",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(interrupts_router)
app.include_router(approvals_router)
app.include_router(ledger_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


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
