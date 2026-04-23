"""HTTP client for Deliberate REST API."""
from __future__ import annotations

import os
from typing import Any

import httpx


class DeliberateAPIClient:
    """Thin wrapper around Deliberate server REST API."""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> None:
        self.base_url = (base_url or os.environ.get("DELIBERATE_URL", "http://localhost:4000")).rstrip("/")
        self.api_key = api_key or os.environ.get("DELIBERATE_API_KEY", "")
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={"X-Deliberate-API-Key": self.api_key},
            timeout=30.0,
        )

    async def request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any] | list[Any] | None:
        resp = await self._client.request(method, path, **kwargs)
        if resp.status_code == 204:
            return None
        if resp.status_code >= 400:
            try:
                detail = resp.json().get("detail", resp.text)
            except Exception:
                detail = resp.text
            return {"error": True, "status": resp.status_code, "detail": detail}
        return resp.json()  # type: ignore[no-any-return]

    async def get(self, path: str, **kwargs: Any) -> dict[str, Any] | list[Any] | None:
        return await self.request("GET", path, **kwargs)

    async def post(self, path: str, **kwargs: Any) -> dict[str, Any] | list[Any] | None:
        return await self.request("POST", path, **kwargs)

    async def put(self, path: str, **kwargs: Any) -> dict[str, Any] | list[Any] | None:
        return await self.request("PUT", path, **kwargs)

    async def delete(self, path: str, **kwargs: Any) -> dict[str, Any] | list[Any] | None:
        return await self.request("DELETE", path, **kwargs)
