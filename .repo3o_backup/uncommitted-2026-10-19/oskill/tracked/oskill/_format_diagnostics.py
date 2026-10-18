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


def format_diagnostics(
    diagnostics: list[Any],
    *,
    max_per_file: int = 20,
    include_source: bool = True,
) -> str:
    """将诊断列表格式化为人类可读字符串（纯内存）。

    Args:
        diagnostics: Diagnostic 对象列表（或 dict 列表，含 path/line/message/severity）。
        max_per_file: 每个文件最多显示条数，默认 20。
        include_source: 是否显示 source 字段，默认 True。

    Returns:
        格式化字符串，按文件分组、按严重程度着色。

    Example:
        >>> text = format_diagnostics(diags)
        >>> "error" in text.lower()
        True
    """
    if not diagnostics:
        return "No diagnostics."

    _SEV = {1: "ERROR", 2: "WARN ", 3: "INFO ", 4: "HINT "}
    by_file: dict[str, list] = {}
    for d in diagnostics:
        path = getattr(d, "path", None) or (d.get("path", "") if isinstance(d, dict) else "")
        by_file.setdefault(path, []).append(d)

    parts = []
    for path, items in sorted(by_file.items()):
        parts.append(f"\n{path}:")
        for item in items[:max_per_file]:
            if hasattr(item, "line"):
                line, char = item.line + 1, item.character  # pragma: no cover
                sev = _SEV.get(item.severity, "?    ")  # pragma: no cover
                msg = item.message  # pragma: no cover
                src = (
                    f" [{item.source}]" if include_source and item.source else ""
                )  # pragma: no cover
            else:
                line = item.get("line", 0) + 1
                char = item.get("character", 0)
                sev = _SEV.get(item.get("severity", 1), "?    ")
                msg = item.get("message", "")
                src = f" [{item['source']}]" if include_source and item.get("source") else ""
            parts.append(f"  {sev} {line}:{char}  {msg}{src}")
        if len(items) > max_per_file:
            parts.append(f"  ... and {len(items) - max_per_file} more")

    return "\n".join(parts).strip()
