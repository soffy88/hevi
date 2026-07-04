from __future__ import annotations

from typing import Any

from hevi.gallery.repository import GalleryRepository


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
