"""StylePack API —— 可实例化 + 版本化的风格资产。设计 §3 L2。"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from obase.persistence import PgPool
from pydantic import BaseModel

from hevi.auth.dependencies import get_current_user
from hevi.db.pg_pool import get_hevi_pg_pool
from hevi.style.style_service import StylePackRepository, StylePackService

router = APIRouter(prefix="/style-packs", tags=["style-packs"])


async def get_pg_pool() -> PgPool:
    return await get_hevi_pg_pool()


async def get_style_service(
    pool: Annotated[PgPool, Depends(get_pg_pool)],
) -> StylePackService:
    return StylePackService(StylePackRepository(pool))


def _check_owner(resource: dict[str, Any], user: dict[str, Any]) -> None:
    if resource.get("user_id") and resource["user_id"] != str(user["id"]):
        raise HTTPException(status_code=404, detail="StylePack not found")


class StylePackCreateRequest(BaseModel):
    name: str
    base_preset: str = ""
    overrides: dict[str, Any] = {}


class StylePackUpdateRequest(BaseModel):
    overrides: dict[str, Any]


@router.post("")
async def create_style_pack(
    body: StylePackCreateRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    svc: Annotated[StylePackService, Depends(get_style_service)],
) -> dict[str, Any]:
    try:
        return await svc.create_pack(
            name=body.name,
            base_preset=body.base_preset,
            overrides=body.overrides,
            user_id=str(user["id"]),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/{pack_id}")
async def get_style_pack(
    pack_id: str,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    svc: Annotated[StylePackService, Depends(get_style_service)],
) -> dict[str, Any]:
    p = await svc.get_pack(pack_id)
    if p is None:
        raise HTTPException(status_code=404, detail="StylePack not found")
    _check_owner(p, user)
    return p


@router.get("/{pack_id}/resolve")
async def resolve_style_pack(
    pack_id: str,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    svc: Annotated[StylePackService, Depends(get_style_service)],
) -> dict[str, Any]:
    """展开成最终风格 dict(base 预设 + overrides)。"""
    p = await svc.get_pack(pack_id)
    if p is None:
        raise HTTPException(status_code=404, detail="StylePack not found")
    _check_owner(p, user)
    return {"resolved": await svc.resolve(pack_id), "version": p.get("version")}


@router.patch("/{pack_id}")
async def update_style_pack(
    pack_id: str,
    body: StylePackUpdateRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    svc: Annotated[StylePackService, Depends(get_style_service)],
) -> dict[str, Any]:
    """改覆盖 → 版本 +1。"""
    p = await svc.get_pack(pack_id)
    if p is None:
        raise HTTPException(status_code=404, detail="StylePack not found")
    _check_owner(p, user)
    updated = await svc.update_overrides(pack_id, overrides=body.overrides)
    return updated or {}
