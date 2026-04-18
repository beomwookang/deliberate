"""Validate that the DeliberateClient is importable and constructable."""

import pytest

from deliberate.client import DeliberateClient


def test_client_constructable() -> None:
    client = DeliberateClient(base_url="http://localhost:4000", api_key="test-key")
    assert client.base_url == "http://localhost:4000"


@pytest.mark.asyncio
async def test_submit_interrupt_raises() -> None:
    from deliberate.types import InterruptPayload

    client = DeliberateClient(base_url="http://localhost:4000", api_key="test-key")
    payload = InterruptPayload(layout="financial_decision", subject="Test")
    with pytest.raises(NotImplementedError):
        await client.submit_interrupt(payload)
