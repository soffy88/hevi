"""Auto-split from hicode whl."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any

from ._types import (
    ParseOskillError,
    ToolCall,
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


def parse_llm_tool_calls(
    response: dict[str, Any],
) -> list[ToolCall]:
    """从 LLM 响应中解析并校验 tool_use 块列表（纯内存）。

    Args:
        response: LLM 原始响应 dict（含 content 列表）。

    Returns:
        ToolCall 列表（已校验 name + input 字段）。

    Raises:
        ParseOskillError: content 字段格式错误。

    Example:
        >>> calls = parse_llm_tool_calls({"content": [
        ...     {"type": "tool_use", "id": "t1", "name": "bash_exec", "input": {"cmd": "ls"}}
        ... ]})
        >>> calls[0].name
        'bash_exec'
    """
    content = response.get("content", [])
    if not isinstance(content, list):
        raise ParseOskillError(
            f"parse_llm_tool_calls: content must be list, got {type(content).__name__}"
        )

    calls = []
    for block in content:
        if not isinstance(block, dict):
            continue  # pragma: no cover
        if block.get("type") != "tool_use":
            continue
        name = block.get("name", "")
        if not name:
            continue
        tool_id = block.get("id") or str(uuid.uuid4())[:8]
        inp = block.get("input", {})
        if not isinstance(inp, dict):
            # 尝试 JSON 解析
            try:  # pragma: no cover
                inp = json.loads(inp) if isinstance(inp, str) else {}  # pragma: no cover
            except (json.JSONDecodeError, TypeError):  # pragma: no cover
                inp = {}  # pragma: no cover
        calls.append(ToolCall(id=tool_id, name=name, input=inp, raw=block))
    return calls
