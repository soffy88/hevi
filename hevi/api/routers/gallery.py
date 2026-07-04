from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from obase.persistence import PgPool
from pydantic import BaseModel

from hevi.auth.dependencies import get_current_user
from hevi.db.pg_pool import get_hevi_pg_pool
from hevi.gallery.repository import GalleryRepository
from hevi.gallery.service import GalleryService

router = APIRouter(prefix="/gallery", tags=["gallery"])


class GalleryCreateRequest(BaseModel):
    category: str
    title: str
    media_url: str | None = None
    description: str | None = None
    thumbnail_url: str | None = None
    prompt: str = ""
    gen_params: dict[str, Any] = {}
    sort_order: int = 0


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


async def get_pg_pool() -> PgPool:
    return await get_hevi_pg_pool()


async def get_gallery_service(
    pool: Annotated[PgPool, Depends(get_pg_pool)],
) -> GalleryService:
    return GalleryService(GalleryRepository(pool))


@router.get("")
async def list_gallery(
    svc: Annotated[GalleryService, Depends(get_gallery_service)],
    category: str | None = None,
) -> dict[str, Any]:
    rows = await svc.list_gallery(category=category)
    items = [_row_to_item(dict(r)) for r in rows]
    categories = list({it["category"] for it in items})
    return {"items": items, "categories": categories}


@router.post("")
async def create_gallery_item(
    body: GalleryCreateRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    svc: Annotated[GalleryService, Depends(get_gallery_service)],
) -> dict[str, Any]:
    """投稿:登录用户把成片上墙(即时可见)。"""
    try:
        row = await svc.create_gallery_item(
            category=body.category,
            title=body.title,
            media_url=body.media_url,
            description=body.description,
            thumbnail_url=body.thumbnail_url,
            prompt=body.prompt,
            gen_params=body.gen_params,
            sort_order=body.sort_order,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    return _row_to_item(dict(row))


@router.get("/{item_id}")
async def get_gallery_item(
    item_id: str,
    svc: Annotated[GalleryService, Depends(get_gallery_service)],
) -> dict[str, Any]:
    row = await svc.get_gallery_item(item_id)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")
    return _row_to_item(dict(row))
