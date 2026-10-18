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


def match_permission_rule(
    tool_call: dict[str, Any],
    *,
    allowed_tools: list[str] | None = None,
    denied_tools: list[str] | None = None,
    mode: str = "default",
) -> str:
    """权限决策算法（纯内存）。

    返回 "allow" | "deny" | "ask"。

    优先级：denied > allowed > mode 规则 > ask。

    Args:
        tool_call: 含 name 字段的工具调用 dict。
        allowed_tools: 允许的工具名 glob 模式列表。
        denied_tools: 拒绝的工具名 glob 模式列表。
        mode: "default" | "acceptEdits" | "plan" | "bypass"。

    Returns:
        "allow" | "deny" | "ask"

    Example:
        >>> match_permission_rule({"name": "bash_exec"}, mode="plan")
        'deny'
    """
    name = tool_call.get("name", "")
    READ_ONLY = {
        "file_read",
        "dir_list",
        "glob_match",
        "git_status",
        "git_diff",
        "git_log",
        "git_show",
        "git_blame",
        "lsp_diagnostics",
        "lsp_hover",
        "lsp_definition",
        "lsp_references",
        "lsp_document_symbols",
        "lsp_workspace_symbols",
        "lsp_completion",
        "ripgrep_search",
    }

    if mode == "bypass":
        return "allow"

    if mode == "plan":
        return "allow" if name in READ_ONLY else "deny"

    # denied 列表
    for pattern in denied_tools or []:
        if fnmatch.fnmatch(name, pattern):
            return "deny"

    # allowed 列表
    for pattern in allowed_tools or []:
        if fnmatch.fnmatch(name, pattern):
            return "allow"

    if mode == "acceptEdits":
        if name in {"file_write", "file_append", "file_delete"}:
            return "allow"

    return "ask"
