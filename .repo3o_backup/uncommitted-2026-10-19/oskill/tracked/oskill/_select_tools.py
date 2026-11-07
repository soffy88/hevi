"""Auto-split from hicode whl."""

from __future__ import annotations

import re
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


def select_tools(
    task: str,
    *,
    available: list[dict[str, Any]],
    max_tools: int = 10,
    mode: str = "build",
) -> list[dict[str, Any]]:
    """根据任务描述和模式选择最相关的工具子集（纯内存）。

    策略：关键词匹配 + 模式过滤（plan 模式排除写操作工具）。

    Args:
        task: 任务描述字符串。
        available: 工具 schema 列表（含 name / description）。
        max_tools: 最多返回工具数，默认 10。
        mode: "build" 或 "plan"。

    Returns:
        排序后的工具 schema 子集（最多 max_tools 个）。

    Example:
        >>> tools = select_tools("read a file", available=[...], mode="plan")
        >>> all(t["name"] != "file_write" for t in tools)
        True  # plan 模式排除写操作
    """
    WRITE_TOOLS = {
        "file_write",
        "file_append",
        "file_delete",
        "bash_exec",
        "git_add",
        "git_commit",
        "git_stash",
    }
    task_lower = task.lower()
    task_words = set(re.findall(r"\w+", task_lower))

    scored: list[ToolScore] = []
    for tool in available:
        name = tool.get("name", "")
        desc = tool.get("description", "").lower()

        # plan 模式过滤写操作
        if mode == "plan" and name in WRITE_TOOLS:
            continue

        # 关键词匹配评分
        tool_words = set(re.findall(r"\w+", name.lower() + " " + desc))
        overlap = task_words & tool_words
        score = len(overlap) / max(len(task_words), 1)

        # 名称直接匹配加分
        if any(w in name.lower() for w in task_words):
            score += 0.5

        scored.append(ToolScore(name=name, score=score, reason=f"overlap={len(overlap)}"))

    scored.sort(key=lambda s: s.score, reverse=True)
    selected_names = {s.name for s in scored[:max_tools]}
    return [t for t in available if t.get("name") in selected_names]
