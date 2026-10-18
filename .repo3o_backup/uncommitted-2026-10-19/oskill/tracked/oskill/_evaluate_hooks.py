"""Auto-split from hicode whl."""

from __future__ import annotations

import fnmatch
from typing import Any

from ._types import (
    HookCmd,
)


def _to_str_list(v: Any) -> list[str]:
    if isinstance(v, list):
        return [str(x) for x in v]
    return []


def _to_dict_list(v: Any) -> list[dict]:
    if isinstance(v, list):
        return [x for x in v if isinstance(x, dict)]
    return []


def evaluate_hooks(
    event: str,
    payload: dict[str, Any],
    *,
    hook_specs: list[dict[str, Any]],
) -> list[HookCmd]:
    """评估哪些 hook 在此事件 + payload 上触发（纯内存）。

    实际执行由调用方调 run_hook oprim 完成，oskill 只做"应该触发哪些"的纯判断。

    Args:
        event: 事件名，如 "PreToolUse"。
        payload: 事件 payload，含 tool / type 等字段。
        hook_specs: hook 定义列表，每项含 event / command / matcher（可选 glob）。

    Returns:
        应触发的 HookCmd 列表（已过滤 + 排序）。

    Example:
        >>> cmds = evaluate_hooks("PreToolUse", {"tool": "bash_exec"},
        ...     hook_specs=[{"event": "PreToolUse", "command": "/hook.sh", "matcher": "bash_*"}])
        >>> len(cmds)
        1
    """
    tool_name = payload.get("tool", payload.get("type", ""))
    matched: list[HookCmd] = []

    for spec in hook_specs:
        if spec.get("event") != event:
            continue
        matcher = spec.get("matcher")
        command = spec.get("command", "")
        if not command:
            continue
        if matcher is None or fnmatch.fnmatch(tool_name, matcher):
            matched.append(HookCmd(event=event, command=command, matcher=matcher))

    return matched


def _to_str_list(v: Any) -> list[str]:
    if isinstance(v, list):
        return [str(x) for x in v]
    return []


def _to_dict_list(v: Any) -> list[dict]:
    if isinstance(v, list):
        return [x for x in v if isinstance(x, dict)]
    return []
