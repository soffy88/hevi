"""Provider Presets 预置策略查询路由 (Frontend SPEC v6.0 §2.4)。

前端不再维护 Provider 管理表单,只向这里查询预置列表/详情,
传 preset 名称或预设级别即可在生成层解析为完整策略。
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException

from hevi.auth.dependencies import get_current_user
from hevi.core.config import settings
from hevi.obase.provider_presets import (
    PRESET_LEVELS,
    get_preset,
    list_presets,
)

router = APIRouter(prefix="/providers", tags=["providers"])


def _plugin_catalog() -> tuple[Any, str]:
    """加载 B5 可编程供应商插件目录(每次调用重读 + mtime 缓存)。

    返回 (catalog, error_msg)。未配置目录/目录缺失 → 空目录 + 提示。
    """
    from hevi.providers.plugin_config import load_catalog

    base = settings.provider_plugin_dir.strip()
    if not base:
        return (None, "PROVIDER_PLUGIN_DIR 未配置(B5 插件加载未启用)")
    path = Path(base)
    if not path.exists():
        return (None, f"插件目录不存在: {path}")
    return (load_catalog(path), "")


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


@router.get("/plugins")
async def list_provider_plugins(
    tool: str | None = None,
    _user: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    """列出 B5 可编程供应商插件(能力声明文件目录)。

    可选 tool 过滤(如 video/shot / tts/narration), 返回声明 + 复用 A1 评分层
    的加权分(降序), 供路由/UI 直接消费。
    """
    from hevi.providers.plugin_config import score_plugins

    catalog, err = _plugin_catalog()
    if catalog is None:
        return {"plugins": [], "total": 0, "enabled": False, "note": err}
    decls = catalog.decls
    if tool:
        decls = [d for d in decls if d.tool == tool]
    scored = score_plugins(decls, tool or "") if decls else []
    # 无 tool 过滤时不重复评分(score_plugins 按 tool 精确匹配), 直接返回声明
    if not tool:
        scored = [{**d.model_dump(), "weighted_score": None} for d in decls]
    return {"plugins": scored, "total": len(scored), "enabled": True, "tool": tool}


@router.get("/plugins/{provider_id}")
async def get_provider_plugin(
    provider_id: str,
    _user: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    """单插件详情(含声明与评分上下文)。"""
    catalog, err = _plugin_catalog()
    if catalog is None:
        raise HTTPException(status_code=404, detail=err or "plugins disabled")
    for d in catalog.decls:
        if d.id == provider_id:
            from hevi.providers.plugin_config import score_plugins

            scored = score_plugins([d], d.tool)
            return {
                **d.model_dump(),
                "score": scored[0] if scored else None,
            }
    raise HTTPException(status_code=404, detail=f"unknown plugin: {provider_id}")
