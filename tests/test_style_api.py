"""StylePack API 路由测试 —— draft-from-reference 端点(HEVI 路线图 Phase3 #38)。"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from hevi.auth.dependencies import get_current_user

_AUTH_USER = {"id": str(uuid.uuid4()), "is_active": True}


@pytest.mark.asyncio
async def test_draft_from_reference_requires_auth(client: Any) -> None:
    resp = await client.post(
        "/api/style-packs/draft-from-reference",
        files={"file": ("ref.png", b"\x89PNG\r\n", "image/png")},
    )
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_draft_from_reference_rejects_empty_file(client: Any) -> None:
    from hevi.api.main import app

    app.dependency_overrides[get_current_user] = lambda: _AUTH_USER
    resp = await client.post(
        "/api/style-packs/draft-from-reference",
        files={"file": ("ref.png", b"", "image/png")},
    )
    app.dependency_overrides.clear()
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_draft_from_reference_503_when_vlm_unavailable(client: Any) -> None:
    from hevi.api.main import app

    app.dependency_overrides[get_current_user] = lambda: _AUTH_USER
    with patch("hevi.providers.local_qwen_vl_adapter.vl_model_available", return_value=False):
        resp = await client.post(
            "/api/style-packs/draft-from-reference",
            files={"file": ("ref.png", b"\x89PNG\r\n", "image/png")},
        )
    app.dependency_overrides.clear()
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_draft_from_reference_returns_parsed_draft(client: Any) -> None:
    from hevi.api.main import app

    app.dependency_overrides[get_current_user] = lambda: _AUTH_USER
    with (
        patch("hevi.providers.local_qwen_vl_adapter.vl_model_available", return_value=True),
        patch(
            "hevi.style.draft_from_reference.draft_style_from_reference",
            new_callable=AsyncMock,
            return_value={
                "style": "cinematic",
                "lighting": "low-key",
                "camera": "slow dolly",
                "color_grade": "teal orange",
            },
        ),
    ):
        resp = await client.post(
            "/api/style-packs/draft-from-reference",
            files={"file": ("ref.png", b"\x89PNG\r\n", "image/png")},
        )
    app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json()["style"] == "cinematic"
