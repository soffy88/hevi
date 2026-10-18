"""Auto-split from hicode whl."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ._types import (
    ConfigOskillError,
    PluginManifest,
)


@dataclass
class ToolScore:
    name: str
    score: float
    reason: str


@dataclass
class HookCmd:
    event: str
    command: str
    matcher: str | None


def compose_plugin_manifest(
    bundle: dict[str, Any],
) -> PluginManifest:
    """解析插件 bundle dict 为 PluginManifest（纯内存）。

    Args:
        bundle: 插件定义 dict，含 name/version/skills/subagents/commands/hooks/mcp_servers。

    Returns:
        PluginManifest（已校验必填字段）。

    Raises:
        ConfigOskillError: name 字段缺失。

    Example:
        >>> manifest = compose_plugin_manifest({
        ...     "name": "my_plugin", "version": "1.0",
        ...     "skills": ["refactor_python"],
        ... })
        >>> manifest.name
        'my_plugin'
    """
    name = bundle.get("name", "")
    if not name:
        raise ConfigOskillError("compose_plugin_manifest: 'name' field is required")

    return PluginManifest(
        name=name,
        version=str(bundle.get("version", "0.1.0")),
        skills=_to_str_list(bundle.get("skills", [])),
        subagents=_to_str_list(bundle.get("subagents", [])),
        commands=_to_dict_list(bundle.get("commands", [])),
        hooks=_to_dict_list(bundle.get("hooks", [])),
        mcp_servers=_to_dict_list(bundle.get("mcp_servers", [])),
    )


def _to_str_list(v: Any) -> list[str]:
    if isinstance(v, list):
        return [str(x) for x in v]
    return []


def _to_dict_list(v: Any) -> list[dict]:
    if isinstance(v, list):
        return [x for x in v if isinstance(x, dict)]
    return []
