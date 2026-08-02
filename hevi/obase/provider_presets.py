"""obase.ProviderRegistry 预置策略表 (Frontend SPEC v6.0 §2.4)。

Provider Presets 从 ViMax 前端管理表单下沉到后端 base 层:
前端仅需传 preset 名称或预设级别(economy/fast/balanced/premium),
由本模块解析为完整的 provider 路由/成本/上下文/锁脸策略。

设计:
- 预置名为稳定标识(wan_local / fal_fast / autocameo_cloud / veo3_cinematic …),
  与 hevi/providers/registry.py 里注册的 provider 名称对齐;
- `level` 表达预设级别,便于前端按档位筛选(💰 省钱 / ⚡ 极速 / ⚖️ 均衡 / 💎 旗舰);
- `strategy` 是生成层消费的归一化策略字典(face_lock 等 AutoCameo 相关开关)。
"""

from __future__ import annotations

from typing import Any

# 预设级别(升序)
PRESET_LEVELS: tuple[str, ...] = ("economy", "fast", "balanced", "premium")

PRESETS: list[dict[str, Any]] = [
    {
        "name": "wan_local",
        "level": "economy",
        "category": "video",
        "provider": "wan_local",
        "description": "本地 Wan·零成本(需本机 GPU),适合草稿/极速单片",
        "base_url": None,
        "context_window": 0,
        "api_key_env": None,
        "strategy": {
            "preferred": "local",
            "max_shots": 8,
            "quality_bar": "standard",
            "face_lock": False,
        },
    },
    {
        "name": "fal_fast",
        "level": "fast",
        "category": "video",
        "provider": "ltx2_cloud",
        "description": "极速草稿(fal·便宜·画质弱)",
        "base_url": "https://queue.fal.run",
        "context_window": 0,
        "api_key_env": "FAL_KEY",
        "strategy": {
            "preferred": "cloud",
            "max_shots": 12,
            "quality_bar": "standard",
            "face_lock": False,
        },
    },
    {
        "name": "autocameo_cloud",
        "level": "balanced",
        "category": "video",
        "provider": "happyhorse_1_1_maas_lock",
        "description": "云端锁脸·人物身份跨镜一致(AutoCameo 照片人物入戏)",
        "base_url": None,
        "context_window": 0,
        "api_key_env": "ALIBABA_MAAS_API_KEY",
        "strategy": {
            "preferred": "cloud",
            "max_shots": 16,
            "quality_bar": "high",
            "face_lock": True,
        },
    },
    {
        "name": "veo3_cinematic",
        "level": "premium",
        "category": "video",
        "provider": "veo3",
        "description": "Veo3 电影感(fal·最写实·最贵)",
        "base_url": "https://queue.fal.run",
        "context_window": 0,
        "api_key_env": "FAL_KEY",
        "strategy": {
            "preferred": "cloud",
            "max_shots": 20,
            "quality_bar": "ultra",
            "face_lock": False,
        },
    },
    {
        "name": "qwen_plus",
        "level": "balanced",
        "category": "llm",
        "provider": "qwen_cloud",
        "description": "云 Qwen(百炼 workspace 端点)·剧本/文案质量好于本地",
        "base_url": None,
        "context_window": 32000,
        "api_key_env": "ALIBABA_MAAS_API_KEY",
        "strategy": {"preferred": "cloud", "model": "qwen-plus"},
    },
    {
        "name": "qwen_local",
        "level": "economy",
        "category": "llm",
        "provider": "llm",
        "description": "本地 Qwen(ollama)·零成本·质量一般",
        "base_url": "http://localhost:11434",
        "context_window": 8192,
        "api_key_env": None,
        "strategy": {"preferred": "local", "model": "qwen2.5vl:7b"},
    },
]

_PRESETS_BY_NAME: dict[str, dict[str, Any]] = {p["name"]: p for p in PRESETS}


def list_presets(category: str | None = None) -> list[dict[str, Any]]:
    """列出预置策略(可按 category 过滤: llm / image / video)。"""
    if category is None:
        return [dict(p) for p in PRESETS]
    return [dict(p) for p in PRESETS if p.get("category") == category]


def get_preset(name: str) -> dict[str, Any] | None:
    """按名称取预置策略;不存在返回 None。"""
    item = _PRESETS_BY_NAME.get(name)
    return dict(item) if item is not None else None


def resolve_preset(name: str | None) -> dict[str, Any]:
    """把 preset 名称解析为完整的 resolved_config(带默认值补齐)。

    供生成层消费:取不到时回落到 `wan_local`(零成本默认),保证前端传
    任意名称都不会把生成打挂。
    """
    item = get_preset(name) or get_preset("wan_local")
    assert item is not None
    return {
        "name": item["name"],
        "level": item["level"],
        "provider": item["provider"],
        "strategy": item["strategy"],
        "api_key_env": item.get("api_key_env"),
    }
