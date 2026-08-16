"""Provider Presets 预置策略查询路由 (Frontend SPEC v6.0 §2.4)。

前端不再维护 Provider 管理表单,只向这里查询预置列表/详情,
传 preset 名称或预设级别即可在生成层解析为完整策略。
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException

from hevi.auth.dependencies import get_current_user
from hevi.obase.provider_presets import (
    PRESET_LEVELS,
    get_preset,
    list_presets,
)

router = APIRouter(prefix="/providers", tags=["providers"])


@router.get("/presets")
async def list_provider_presets(
    category: str | None = None,
    _user: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    """列出 obase.ProviderRegistry 预置策略表(可按 category 过滤)。"""
    presets = list_presets(category)
    return {
        "presets": presets,
        "total": len(presets),
        "levels": list(PRESET_LEVELS),
    }


@router.get("/presets/{name}")
async def get_provider_preset(
    name: str,
    _user: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    """按名称取预置策略详情(含归一化 resolved_config)。"""
    item = get_preset(name)
    if item is None:
        raise HTTPException(status_code=404, detail=f"unknown preset: {name}")
    from hevi.obase.provider_presets import resolve_preset

    return {**item, "resolved_config": resolve_preset(name)}
