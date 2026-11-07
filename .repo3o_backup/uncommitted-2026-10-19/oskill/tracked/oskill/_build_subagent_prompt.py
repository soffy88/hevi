"""Auto-split from hicode whl."""

from __future__ import annotations

import fnmatch
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


def _to_str_list(v: Any) -> list[str]:
    if isinstance(v, list):
        return [str(x) for x in v]
    return []


def _to_dict_list(v: Any) -> list[dict]:
    if isinstance(v, list):
        return [x for x in v if isinstance(x, dict)]
    return []


def build_subagent_prompt(
    subagent_def: dict[str, Any],
    task: str,
    *,
    context: str = "",
    memory: str = "",
) -> dict[str, Any]:
    """根据 subagent 定义生成系统 prompt 和受限工具集（纯内存）。

    Args:
        subagent_def: subagent 定义 dict（含 system_prompt / tools / permissions）。
        task: 主 agent 传递的任务描述。
        context: 主 agent 传递的上下文片段（可选）。
        memory: agent-memory 历史记忆内容（可选）。

    Returns:
        {
            "system": str,           # 完整系统 prompt
            "scoped_tools": list,    # 按 permissions 过滤后的工具 schema
        }

    Example:
        >>> result = build_subagent_prompt(
        ...     {"system_prompt": "You are a tester.", "tools": [...]},
        ...     task="Write unit tests",
        ... )
        >>> "tester" in result["system"]
        True
    """
    base_system = subagent_def.get("system_prompt", "You are a helpful subagent.")
    parts = [base_system.strip()]

    if memory and memory.strip():
        parts.append(f"## Historical Memory\n{memory.strip()}")
    if context and context.strip():
        parts.append(f"## Context from Parent Agent\n{context.strip()}")

    system = "\n\n".join(parts)
    permissions = subagent_def.get("permissions", {})
    mode = permissions.get("mode", "default") if isinstance(permissions, dict) else "default"
    all_tools = subagent_def.get("tools", [])

    # 按 permissions.mode 过滤工具
    READ_ONLY_NAMES = {
        "file_read",
        "dir_list",
        "glob_match",
        "git_status",
        "git_diff",
        "git_log",
        "lsp_diagnostics",
        "lsp_hover",
    }
    if mode == "plan":
        scoped = [t for t in all_tools if t.get("name") in READ_ONLY_NAMES]
    elif mode == "bypass":
        scoped = list(all_tools)
    else:
        allowed = permissions.get("allowed_tools", []) if isinstance(permissions, dict) else []
        denied = permissions.get("denied_tools", []) if isinstance(permissions, dict) else []
        scoped = []
        for tool in all_tools:
            name = tool.get("name", "")
            if any(fnmatch.fnmatch(name, p) for p in denied):
                continue  # pragma: no cover
            if not allowed or any(fnmatch.fnmatch(name, p) for p in allowed):
                scoped.append(tool)

    return {"system": system, "scoped_tools": scoped}


def _to_str_list(v: Any) -> list[str]:
    if isinstance(v, list):
        return [str(x) for x in v]
    return []


def _to_dict_list(v: Any) -> list[dict]:
    if isinstance(v, list):
        return [x for x in v if isinstance(x, dict)]
    return []
