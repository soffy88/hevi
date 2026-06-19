from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from obase.persistence import PgPool

from hevi.db.pg_pool import get_hevi_pg_pool

router = APIRouter(prefix="/gallery", tags=["gallery"])


async def _get_pool(pool: Annotated[PgPool, Depends(get_hevi_pg_pool)]) -> PgPool:
    return pool


def _row_to_item(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "item_id": str(row["id"]),
        "category": row["category"],
        "title": row["title"],
        "description": row.get("description"),
        "media_url": row.get("media_url"),
        "thumbnail_url": row.get("thumbnail_url"),
        "prompt": row.get("prompt", ""),
        "gen_params": row.get("gen_params") or {},
        "sort_order": row.get("sort_order", 0),
    }


@router.get("")
async def list_gallery(
    category: str | None = None,
    pool: PgPool = Depends(_get_pool),
) -> dict[str, Any]:
    async with pool.acquire() as conn:
        if category:
            rows = await conn.fetch(
                "SELECT * FROM showcase_items WHERE is_active = true AND category = $1"
                " ORDER BY sort_order, created_at",
                category,
            )
        else:
            rows = await conn.fetch(
                "SELECT * FROM showcase_items WHERE is_active = true"
                " ORDER BY sort_order, created_at"
            )
    items = [_row_to_item(dict(r)) for r in rows]
    categories = list({it["category"] for it in items})
    return {"items": items, "categories": categories}


@router.get("/{item_id}")
async def get_gallery_item(
    item_id: str,
    pool: PgPool = Depends(_get_pool),
) -> dict[str, Any]:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM showcase_items WHERE id = $1 AND is_active = true",
            item_id,
        )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")
    return _row_to_item(dict(row))
