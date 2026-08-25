from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
from obase.persistence import PgPool, insert_one, query


class StockAssetRepository:
    """User-scoped record of material search results and licence snapshots."""

    def __init__(self, pool: PgPool) -> None:
        self._pool = pool

    async def record_many(self, *, user_id: str, assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
        recorded: list[dict[str, Any]] = []
        for asset in assets:
            provider = str(asset["provider"])
            external_id = str(asset["external_id"])
            existing = await query(
                self._pool,
                sql=(
                    "SELECT * FROM stock_assets WHERE user_id = $1 AND provider = $2 "
                    "AND external_id = $3"
                ),
                params=[user_id, provider, external_id],
                limit=1,
            )
            if existing:
                recorded.append(existing[0])
                continue
            data = {
                "id": uuid.uuid4(),
                "user_id": user_id,
                "provider": provider,
                "external_id": external_id,
                "media_type": asset["media_type"],
                "title": asset.get("title", ""),
                "source_url": asset["source_url"],
                "preview_url": asset.get("preview_url"),
                "thumbnail_url": asset.get("thumbnail_url"),
                "license_json": asset["license"],
                "query_text": asset["query"],
                "created_at": datetime.now(UTC).replace(tzinfo=None),
            }
            asset_id = await insert_one(self._pool, table="stock_assets", data=data, returning="id")
            rows = await query(
                self._pool,
                sql="SELECT * FROM stock_assets WHERE id = $1",
                params=[asset_id],
                limit=1,
            )
            recorded.append(rows[0] if rows else {**data, "id": asset_id})
        return recorded

    async def list_for_user(self, *, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
        return await query(
            self._pool,
            sql="SELECT * FROM stock_assets WHERE user_id = $1 ORDER BY created_at DESC",
            params=[user_id],
            limit=limit,
        )


"""Pexels-backed stock search with explicit source and licence provenance."""


_PEXELS_API = "https://api.pexels.com"
_PEXELS_LICENSE = {
    "name": "Pexels License",
    "url": "https://www.pexels.com/license/",
    "attribution_required": False,
    "commercial_use": True,
}


class StockProviderUnavailable(RuntimeError):
    pass


class StockProviderError(RuntimeError):
    pass


class StockSearchService:
    def __init__(
        self,
        repository: StockAssetRepository,
        *,
        api_key: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._repository = repository
        self._api_key = (api_key if api_key is not None else os.getenv("PEXELS_API_KEY", "")).strip()
        self._client = client

    @property
    def available(self) -> bool:
        return bool(self._api_key)

    async def search(
        self,
        *,
        user_id: str,
        query: str,
        media_type: str,
        count: int,
    ) -> list[dict[str, Any]]:
        if not self.available:
            raise StockProviderUnavailable("PEXELS_API_KEY 未配置")
        if media_type not in {"video", "image"}:
            raise ValueError("media_type 仅支持 video 或 image")
        path = "/videos/search" if media_type == "video" else "/v1/search"
        params: dict[str, str | int] = {"query": query, "per_page": min(max(count, 1), 80)}
        try:
            if self._client is not None:
                response = await self._client.get(
                    f"{_PEXELS_API}{path}", params=params, headers={"Authorization": self._api_key}
                )
            else:
                async with httpx.AsyncClient(timeout=20.0) as client:
                    response = await client.get(
                        f"{_PEXELS_API}{path}", params=params, headers={"Authorization": self._api_key}
                    )
        except httpx.HTTPError as exc:
            raise StockProviderError(f"Pexels 请求失败：{exc}") from exc
        if response.status_code in {401, 403}:
            raise StockProviderUnavailable("Pexels 授权失败，请检查 PEXELS_API_KEY")
        if response.status_code >= 400:
            raise StockProviderError(f"Pexels 返回 HTTP {response.status_code}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise StockProviderError("Pexels 返回了无效响应") from exc
        items = payload.get("videos" if media_type == "video" else "photos", [])
        if not isinstance(items, list):
            raise StockProviderError("Pexels 响应缺少素材列表")
        assets = [self._normalize(item, query=query, media_type=media_type) for item in items]
        return await self._repository.record_many(user_id=user_id, assets=assets)

    @staticmethod
    def _normalize(item: Any, *, query: str, media_type: str) -> dict[str, Any]:
        if not isinstance(item, dict) or item.get("id") is None or not item.get("url"):
            raise StockProviderError("Pexels 返回的素材缺少 ID 或来源链接")
        if media_type == "video":
            files = item.get("video_files") or []
            preview_url = next(
                (str(file["link"]) for file in files if isinstance(file, dict) and file.get("link")),
                None,
            )
            thumbnail = item.get("image")
        else:
            src = item.get("src") or {}
            preview_url = src.get("large") or src.get("original")
            thumbnail = src.get("medium") or preview_url
        photographer_value = item.get("user") or item.get("photographer") or "Pexels contributor"
        photographer = (
            photographer_value.get("name", "Pexels contributor")
            if isinstance(photographer_value, dict)
            else str(photographer_value)
        )
        return {
            "provider": "pexels",
            "external_id": str(item["id"]),
            "media_type": media_type,
            "title": f"{query} · {photographer}",
            "source_url": str(item["url"]),
            "preview_url": str(preview_url) if preview_url else None,
            "thumbnail_url": str(thumbnail) if thumbnail else None,
            "license": {**_PEXELS_LICENSE, "provider": "pexels", "author": str(photographer)},
            "query": query,
        }
