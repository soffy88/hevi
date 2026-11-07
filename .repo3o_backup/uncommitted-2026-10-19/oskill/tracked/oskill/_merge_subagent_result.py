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


def merge_subagent_result(
    summaries: list[dict[str, Any]],
    *,
    task: str = "",
    max_length: int = 8000,
) -> str:
    """将多个 subagent 返回的摘要合并为主 agent context delta（纯内存）。

    Args:
        summaries: run_subagent 返回的 dict 列表（含 summary / subagent_name / status）。
        task: 原始任务描述（用于摘要标题）。
        max_length: 合并结果最大字符数，超出时截断。

    Returns:
        合并后的上下文字符串（注入主 agent messages）。

    Example:
        >>> ctx = merge_subagent_result([
        ...     {"subagent_name": "tester", "summary": "Tests written.", "status": "completed"}
        ... ])
        >>> "tester" in ctx
        True
    """
    if not summaries:
        return ""

    parts: list[str] = []
    if task:
        parts.append(f"## Subagent Results for: {task}\n")

    for r in summaries:
        name = r.get("subagent_name", "unknown")
        status = r.get("status", "unknown")
        summary = r.get("summary", "")
        cost = r.get("cost_usd", 0.0)
        iters = r.get("iterations", 0)
        meta = f"[{status}, {iters} iters, ${cost:.4f}]"
        parts.append(f"### {name} {meta}\n{summary}")

    result = "\n\n".join(parts)
    if len(result) > max_length:
        result = result[:max_length] + "\n...[truncated]"
    return result
