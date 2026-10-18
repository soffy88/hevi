"""Auto-split from hicode whl."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


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


def merge_config(
    global_: dict[str, Any],
    project: dict[str, Any],
    agents_md: dict[str, Any] | None = None,
    *,
    env_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """分层合并配置（纯内存）。

    优先级（高→低）：env_overrides > agents_md > project > global_

    Args:
        global_: 全局配置 dict。
        project: 项目级配置 dict。
        agents_md: AGENTS.md 解析出的配置 dict（可选）。
        env_overrides: 环境变量覆盖 dict（最高优先级，可选）。

    Returns:
        合并后的有效配置 dict。

    Example:
        >>> cfg = merge_config({"model": "opus"}, {"model": "sonnet"})
        >>> cfg["model"]
        'sonnet'  # 项目级覆盖全局
    """
    result: dict[str, Any] = {}
    for src in [global_, project, agents_md or {}, env_overrides or {}]:
        if isinstance(src, dict):
            result.update(src)
    return result
