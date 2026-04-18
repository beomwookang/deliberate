"""FastAPI application entry point.

Currently only serves the health endpoint. Route stubs for interrupts,
approvals, and ledger exist as empty modules in api/routes/.
"""

from fastapi import FastAPI

app = FastAPI(
    title="Deliberate",
    description="The approval layer for LangGraph agents",
    version="0.0.1",
)


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
