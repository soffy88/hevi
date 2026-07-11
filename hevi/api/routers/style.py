"""StylePack API —— 可实例化 + 版本化的风格资产。设计 §3 L2。"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from obase.persistence import PgPool
from pydantic import BaseModel

from hevi.auth.dependencies import get_current_user
from hevi.db.pg_pool import get_hevi_pg_pool
from hevi.style.style_service import StylePackRepository, StylePackService

router = APIRouter(prefix="/style-packs", tags=["style-packs"])

_MAX_REFERENCE_BYTES = 50 * 1024 * 1024  # 50MB(参考视频比参考图大得多)


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


@router.post("/draft-from-reference")
async def draft_style_pack_from_reference(
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    file: Annotated[UploadFile, File(description="参考图/视频,VLM 拆解出风格草稿")],
) -> dict[str, str]:
    """StylePack 创建入口(HEVI 路线图 Phase3 #38):参考图/视频 → VLM 拆解出
    style/lighting/camera/color_grade 短语草稿。**不落库**——前端展示草稿供用户
    确认/编辑后,再调 POST /style-packs 用确认后的字段真正建 StylePack。
    """
    data = await file.read()
    if not data:
        raise HTTPException(status_code=422, detail="空文件")
    if len(data) > _MAX_REFERENCE_BYTES:
        raise HTTPException(status_code=413, detail="文件过大(上限 50MB)")

    import tempfile
    from pathlib import Path

    from hevi.style.draft_from_reference import StyleDraftError, draft_style_from_reference

    suffix = Path(file.filename or "").suffix or ".png"
    with tempfile.NamedTemporaryFile(suffix=suffix) as tmp:
        tmp.write(data)
        tmp.flush()

        try:
            from hevi.providers.local_qwen_vl_adapter import (
                local_qwen_vl_adapter,
                vl_model_available,
            )

            if not vl_model_available():
                raise HTTPException(status_code=503, detail="本地视觉模型当前不可用")
            vlm = local_qwen_vl_adapter
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=503, detail=f"本地视觉模型不可用: {e}") from e

        try:
            return await draft_style_from_reference(Path(tmp.name), vlm=vlm)
        except StyleDraftError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e


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
