from unittest.mock import patch

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health(client: AsyncClient) -> None:
    response = await client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["version"] == "6.0.0"


@pytest.mark.asyncio
async def test_health_ready_local_mode(client: AsyncClient) -> None:
    with patch("hevi.api.main.settings.local_mode", True):
        response = await client.get("/api/health/ready")
    assert response.status_code == 200
    body = response.json()
    # D7-I: readiness reports database + authority stores + optional capabilities.
    assert body["status"] == "ready"
    assert body["database"] == "ok"
    assert body["authority_host_claim"] == "single_host_durable"
    assert set(body["authority_stores"]) == {"identity", "incident"}
    assert all(entry["status"] == "ok" for entry in body["authority_stores"].values())
    # GPU/lip-sync absence must not fail readiness.
    assert body["optional_capabilities"]["gpu"] in ("READY", "OPTIONAL_CAPABILITY_BLOCKED")
