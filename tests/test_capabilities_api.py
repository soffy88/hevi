"""Tests for capabilities API and CapabilityError / validate_params (FIX-15, FIX-16)."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from hevi.api.main import app
from hevi.capabilities import get
from hevi.capabilities.registry import CapabilityError


@pytest.mark.anyio
async def test_get_capabilities_api() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/api/capabilities")
        assert resp.status_code == 200
        data = resp.json()
        assert "capabilities" in data
        names = {c["name"] for c in data["capabilities"]}
        assert "kids.story_gate" in names
        assert "kids.consistency_manifest" in names
        assert "qa.kids_gate" in names


def test_capability_params_validation_error() -> None:
    cap = get("kids.consistency_manifest")
    # 传非法参数格式（缺少 manifest 或类型不对）
    with pytest.raises(CapabilityError):
        cap.validate_params({"wrong": 1})

    story_cap = get("kids.story_gate")
    with pytest.raises(CapabilityError):
        story_cap.validate_params({"story": "not a dict"})
