from __future__ import annotations

from typing import Any

from obase.persistence import PgPool, insert_one, query


class GalleryRepository:
    def __init__(self, pool: PgPool) -> None:
        self._pool = pool

    async def create_gallery_item(self, data: dict[str, Any]) -> str:
        return await insert_one(self._pool, table="showcase_items", data=data, returning="id")

    async def list_gallery(
        self,
        *,
        category: str | None = None,
    ) -> list[dict[str, Any]]:
        conditions = ["is_active = true"]
        params: list[Any] = []
        idx = 1

        if category is not None:
            conditions.append(f"category = ${idx}")
            params.append(category)
            idx += 1

        where = " AND ".join(conditions)
        sql = f"SELECT * FROM showcase_items WHERE {where} ORDER BY sort_order, created_at"
        # limit=0 → no implicit LIMIT is appended, preserving the original
        # "return every active item" behaviour.
        rows: list[dict[str, Any]] = await query(
            self._pool,
            sql=sql,
            params=params if params else None,
            limit=0,
        )
        return rows

    async def get_gallery_item(self, item_id: str) -> dict[str, Any] | None:
        rows: list[dict[str, Any]] = await query(
            self._pool,
            sql="SELECT * FROM showcase_items WHERE id = $1 AND is_active = true",
            params=[item_id],
            limit=1,
        )
        return rows[0] if rows else None
