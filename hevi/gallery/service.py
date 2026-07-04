from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from hevi.gallery.repository import GalleryRepository

# 允许的展示墙分区(与前端 GalleryCategory 对齐)。投稿时校验,挡住脏分区。
VALID_CATEGORIES = frozenset(
    {"long_video", "short_video", "avatar_narration", "animation", "image"}
)


class GalleryService:
    def __init__(self, repo: GalleryRepository) -> None:
        self._repo = repo

    async def list_gallery(
        self,
        *,
        category: str | None = None,
    ) -> list[dict[str, Any]]:
        return await self._repo.list_gallery(category=category)

    async def get_gallery_item(self, item_id: str) -> dict[str, Any] | None:
        return await self._repo.get_gallery_item(item_id)

    async def create_gallery_item(
        self,
        *,
        category: str,
        title: str,
        media_url: str | None = None,
        description: str | None = None,
        thumbnail_url: str | None = None,
        prompt: str = "",
        gen_params: dict[str, Any] | None = None,
        sort_order: int = 0,
    ) -> dict[str, Any]:
        """投稿:成片上墙。校验分区 → 落 showcase_items(即时可见 is_active=true)。"""
        if category not in VALID_CATEGORIES:
            raise ValueError(f"未知分区 {category!r},允许:{sorted(VALID_CATEGORIES)}")
        if not title.strip():
            raise ValueError("title 不能为空")
        item_id = uuid.uuid4().hex  # showcase_items.id 为 String(64)
        data = {
            "id": item_id,
            "category": category,
            "title": title,
            "description": description,
            "media_url": media_url,
            "thumbnail_url": thumbnail_url,
            "prompt": prompt,
            "gen_params": gen_params or {},
            "sort_order": sort_order,
            "is_active": True,
            "created_at": datetime.now(UTC).replace(tzinfo=None),
        }
        await self._repo.create_gallery_item(data)
        return (await self._repo.get_gallery_item(item_id)) or data
