"""The scans API. No database and no broker -- both are stubbed."""

from __future__ import annotations

from httpx import AsyncClient


async def test_an_invalid_url_is_refused_synchronously(client: AsyncClient) -> None:
    """A caller should not have to poll a FAILED scan to learn their URL was unusable."""
    response = await client.post("/api/v1/scans", json={"url": "ext::sh -c whoami"})
    assert response.status_code == 422
    assert "transport" in response.text.lower()


async def test_a_missing_url_is_a_validation_error(client: AsyncClient) -> None:
    response = await client.post("/api/v1/scans", json={})
    assert response.status_code == 422
