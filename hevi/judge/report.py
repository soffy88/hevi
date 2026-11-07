"""Report helpers."""
from __future__ import annotations
from typing import Any


def render_report(data: dict[str, Any]) -> str:
    lines = ["# JUDGE_REPORT", ""]
    for k, v in data.items():
        lines.append(f"## {k}")
        lines.append(str(v))
        lines.append("")
    lines.append("DONE")
    return "\n".join(lines)
