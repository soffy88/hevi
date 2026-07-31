"""供应商热插拔 API - 运行时管理 AI providers。

端点:
- GET /api/providers - 列出所有已注册 providers
- GET /api/providers/yaml - 列出 YAML 配置的 providers
- POST /api/providers/reload - 重载所有 YAML providers
- POST /api/providers - 创建新 provider (写入 YAML)
- PUT /api/providers/{name} - 更新 provider 配置
- DELETE /api/providers/{name} - 删除 provider 配置
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, HTTPException
from obase.provider_registry import ProviderRegistry
from pydantic import BaseModel, Field

from hevi.providers.dynamic_loader import (
    DEFAULT_CONFIG_DIR,
    list_yaml_providers,
    load_all_providers,
    reload_all_providers,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/providers", tags=["providers"])


# ── Request/Response schemas ─────────────────────────────────────────────────


class ProviderConfig(BaseModel):
    """Provider 配置 schema。"""

    category: str = Field(..., description="Provider 类别: llm, video, audio, image_gen, vlm")
    name: str = Field(..., description="Provider 唯一名称")
    adapter: str = Field(..., description="Adapter 类型: openai_compatible, dashscope")
    config: dict[str, Any] = Field(default_factory=dict, description="Adapter 配置参数")
    enabled: bool = Field(default=True, description="是否启用")
    priority: int = Field(default=0, description="优先级 (同类别多个 provider 时)")


class ProviderInfo(BaseModel):
    """Provider 信息 (响应用)。"""

    category: str
    name: str
    source: str  # "builtin" or "yaml"
    config_file: str | None = None
    enabled: bool = True


class ReloadResponse(BaseModel):
    """重载响应。"""

    status: str
    loaded_count: int
    message: str


# ── 端点实现 ─────────────────────────────────────────────────────────────────


@router.get("", response_model=list[ProviderInfo])
async def list_all_providers() -> list[dict[str, Any]]:
    """列出所有已注册的 providers (builtin + yaml)。"""
    providers: list[dict[str, Any]] = []

    # 从 ProviderRegistry 获取所有已注册的
    registry_data = ProviderRegistry.get_all() if hasattr(ProviderRegistry, "get_all") else {}

    # 如果 ProviderRegistry 没有 get_all 方法,尝试列出常见类别
    categories = ["llm", "video", "audio", "image_gen", "vlm"]

    for category in categories:
        try:
            # 尝试获取该类别的所有 providers
            if hasattr(ProviderRegistry, "list_providers"):
                names = ProviderRegistry.list_providers(category)
            else:
                # 回退:从 YAML 配置推断
                names = []
        except Exception:
            names = []

        for name in names:
            providers.append({
                "category": category,
                "name": name,
                "source": "builtin",
                "config_file": None,
                "enabled": True,
            })

    # 添加 YAML 配置的 providers
    yaml_providers = list_yaml_providers()
    for yp in yaml_providers:
        providers.append({
            "category": yp["category"],
            "name": yp["name"],
            "source": "yaml",
            "config_file": yp["config_file"],
            "enabled": yp["enabled"],
        })

    return providers


@router.get("/yaml", response_model=list[dict[str, Any]])
async def list_yaml_providers_endpoint() -> list[dict[str, Any]]:
    """列出所有 YAML 配置的 providers (不加载,只读元数据)。"""
    return list_yaml_providers()


@router.post("/reload", response_model=ReloadResponse)
async def reload_providers() -> dict[str, Any]:
    """重载所有 YAML providers。"""
    try:
        count = reload_all_providers()
        return {
            "status": "success",
            "loaded_count": count,
            "message": f"Reloaded {count} YAML providers",
        }
    except Exception as e:
        logger.error(f"Failed to reload providers: {e}")
        raise HTTPException(status_code=500, detail=f"Reload failed: {e}")


@router.post("", status_code=201)
async def create_provider(config: ProviderConfig) -> dict[str, Any]:
    """创建新 provider 配置 (写入 YAML 文件)。"""
    config_dir = DEFAULT_CONFIG_DIR
    config_dir.mkdir(parents=True, exist_ok=True)

    yaml_file = config_dir / f"{config.name}.yaml"

    if yaml_file.exists():
        raise HTTPException(
            status_code=409,
            detail=f"Provider '{config.name}' already exists. Use PUT to update.",
        )

    # 写入 YAML
    yaml_data = config.model_dump()
    try:
        with open(yaml_file, "w", encoding="utf-8") as f:
            yaml.dump(yaml_data, f, allow_unicode=True, default_flow_style=False)

        logger.info(f"Created provider config: {yaml_file}")

        # 立即加载
        load_all_providers()

        return {
            "status": "created",
            "name": config.name,
            "config_file": str(yaml_file),
        }
    except Exception as e:
        logger.error(f"Failed to create provider config: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create config: {e}")


@router.put("/{name}")
async def update_provider(name: str, config: ProviderConfig) -> dict[str, Any]:
    """更新 provider 配置 (覆盖 YAML 文件)。"""
    if config.name != name:
        raise HTTPException(
            status_code=400,
            detail=f"Name mismatch: URL has '{name}', body has '{config.name}'",
        )

    config_dir = DEFAULT_CONFIG_DIR
    config_dir.mkdir(parents=True, exist_ok=True)

    yaml_file = config_dir / f"{name}.yaml"

    # 写入 YAML (覆盖)
    yaml_data = config.model_dump()
    try:
        with open(yaml_file, "w", encoding="utf-8") as f:
            yaml.dump(yaml_data, f, allow_unicode=True, default_flow_style=False)

        logger.info(f"Updated provider config: {yaml_file}")

        # 重新加载
        reload_all_providers()

        return {
            "status": "updated",
            "name": name,
            "config_file": str(yaml_file),
        }
    except Exception as e:
        logger.error(f"Failed to update provider config: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to update config: {e}")


@router.delete("/{name}")
async def delete_provider(name: str) -> dict[str, Any]:
    """删除 provider 配置。"""
    config_dir = DEFAULT_CONFIG_DIR
    yaml_file = config_dir / f"{name}.yaml"

    if not yaml_file.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Provider '{name}' not found",
        )

    try:
        yaml_file.unlink()
        logger.info(f"Deleted provider config: {yaml_file}")

        # 重新加载 (移除已删除的)
        reload_all_providers()

        return {
            "status": "deleted",
            "name": name,
        }
    except Exception as e:
        logger.error(f"Failed to delete provider config: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete config: {e}")


@router.get("/{category}/{name}")
async def get_provider_config(category: str, name: str) -> dict[str, Any]:
    """获取指定 provider 的配置详情。"""
    config_dir = DEFAULT_CONFIG_DIR
    yaml_file = config_dir / f"{name}.yaml"

    if not yaml_file.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Provider '{name}' not found",
        )

    try:
        with open(yaml_file, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)

        return {
            "category": category,
            "name": name,
            "config": config,
            "config_file": str(yaml_file),
        }
    except Exception as e:
        logger.error(f"Failed to read provider config: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to read config: {e}")
