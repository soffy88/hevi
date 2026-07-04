"""Gallery module tests — repository, service, and API routes.

Gallery is a public, read-only showcase backed by the ``showcase_items`` table.
Mirrors the fixture/mock style of ``tests/test_subjects.py``.
"""

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hevi.gallery.repository import GalleryRepository
from hevi.gallery.service import GalleryService

# ── Helpers ──────────────────────────────────────────────────────────────────

_ITEM_ID = str(uuid.uuid4())

_STORED: dict[str, Any] = {
    "id": _ITEM_ID,
    "category": "portrait",
    "title": "Sunset",
    "description": "A warm sunset",
    "media_url": "media/sunset.mp4",
    "thumbnail_url": "thumb/sunset.jpg",
    "prompt": "golden hour portrait",
    "gen_params": {"steps": 20},
    "sort_order": 1,
    "is_active": True,
}


def _make_repo() -> tuple[GalleryRepository, MagicMock]:
    pool = MagicMock()
    return GalleryRepository(pool), pool


def _make_svc(repo: GalleryRepository | None = None) -> GalleryService:
    if repo is None:
        repo, _ = _make_repo()
    return GalleryService(repo)


# ── 1. Repository — list_gallery ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_gallery_no_category() -> None:
    repo, _ = _make_repo()
    with patch(
        "hevi.gallery.repository.query", new_callable=AsyncMock, return_value=[_STORED]
    ) as m:
        rows = await repo.list_gallery()
    assert rows == [_STORED]
    sql_used: str = m.call_args.kwargs.get("sql", "")
    assert "is_active = true" in sql_used
    # No category filter → no params passed.
    assert m.call_args.kwargs.get("params") is None


@pytest.mark.asyncio
async def test_list_gallery_with_category() -> None:
    repo, _ = _make_repo()
    with patch(
        "hevi.gallery.repository.query", new_callable=AsyncMock, return_value=[_STORED]
    ) as m:
        await repo.list_gallery(category="portrait")
    sql_used: str = m.call_args.kwargs.get("sql", "")
    assert "category = $1" in sql_used
    assert m.call_args.kwargs.get("params") == ["portrait"]


@pytest.mark.asyncio
async def test_list_gallery_empty() -> None:
    repo, _ = _make_repo()
    with patch("hevi.gallery.repository.query", new_callable=AsyncMock, return_value=[]):
        rows = await repo.list_gallery()
    assert rows == []


# ── 2. Repository — get_gallery_item ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_gallery_item_found() -> None:
    repo, _ = _make_repo()
    with patch(
        "hevi.gallery.repository.query", new_callable=AsyncMock, return_value=[_STORED]
    ) as m:
        row = await repo.get_gallery_item(_ITEM_ID)
    assert row == _STORED
    assert m.call_args.kwargs.get("params") == [_ITEM_ID]


@pytest.mark.asyncio
async def test_get_gallery_item_missing_returns_none() -> None:
    repo, _ = _make_repo()
    with patch("hevi.gallery.repository.query", new_callable=AsyncMock, return_value=[]):
        row = await repo.get_gallery_item(_ITEM_ID)
    assert row is None


# ── 3. Service delegates to repository ───────────────────────────────────────


@pytest.mark.asyncio
async def test_service_list_delegates() -> None:
    repo, _ = _make_repo()
    with patch.object(repo, "list_gallery", new_callable=AsyncMock, return_value=[_STORED]) as m:
        svc = _make_svc(repo)
        result = await svc.list_gallery(category="portrait")
    assert result == [_STORED]
    m.assert_awaited_once_with(category="portrait")


@pytest.mark.asyncio
async def test_service_get_delegates() -> None:
    repo, _ = _make_repo()
    with patch.object(repo, "get_gallery_item", new_callable=AsyncMock, return_value=None) as m:
        svc = _make_svc(repo)
        result = await svc.get_gallery_item(_ITEM_ID)
    assert result is None
    m.assert_awaited_once_with(_ITEM_ID)


# ── 4. API routes ────────────────────────────────────────────────────────────


def _mock_svc() -> GalleryService:
    pool = MagicMock()
    return GalleryService(GalleryRepository(pool))


@pytest.mark.asyncio
async def test_api_list_gallery(client: Any) -> None:
    from hevi.api.main import app
    from hevi.api.routers.gallery import get_gallery_service

    svc = _mock_svc()
    with patch.object(svc, "list_gallery", new_callable=AsyncMock, return_value=[_STORED]):
        app.dependency_overrides[get_gallery_service] = lambda: svc
        resp = await client.get("/api/gallery")
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    body = resp.json()
    assert body["items"][0]["item_id"] == _ITEM_ID
    assert body["items"][0]["title"] == "Sunset"
    assert body["categories"] == ["portrait"]


@pytest.mark.asyncio
async def test_api_list_gallery_empty(client: Any) -> None:
    from hevi.api.main import app
    from hevi.api.routers.gallery import get_gallery_service

    svc = _mock_svc()
    with patch.object(svc, "list_gallery", new_callable=AsyncMock, return_value=[]):
        app.dependency_overrides[get_gallery_service] = lambda: svc
        resp = await client.get("/api/gallery")
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json() == {"items": [], "categories": []}


@pytest.mark.asyncio
async def test_api_get_gallery_item(client: Any) -> None:
    from hevi.api.main import app
    from hevi.api.routers.gallery import get_gallery_service

    svc = _mock_svc()
    with patch.object(svc, "get_gallery_item", new_callable=AsyncMock, return_value=_STORED):
        app.dependency_overrides[get_gallery_service] = lambda: svc
        resp = await client.get(f"/api/gallery/{_ITEM_ID}")
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json()["item_id"] == _ITEM_ID


@pytest.mark.asyncio
async def test_api_get_gallery_item_404(client: Any) -> None:
    from hevi.api.main import app
    from hevi.api.routers.gallery import get_gallery_service

    svc = _mock_svc()
    with patch.object(svc, "get_gallery_item", new_callable=AsyncMock, return_value=None):
        app.dependency_overrides[get_gallery_service] = lambda: svc
        resp = await client.get(f"/api/gallery/{_ITEM_ID}")
        app.dependency_overrides.clear()
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Item not found"
