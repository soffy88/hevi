"""Auto-split from hicode whl."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from ._types import (
    TodoItem,
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


def plan_to_todos(
    plan: list[dict[str, Any]] | str,
    *,
    priority_map: dict[str, str] | None = None,
) -> list[TodoItem]:
    """将计划（SubTask 列表或文本）转为 TodoItem 列表（纯内存）。

    Args:
        plan: SubTask dict 列表，或文本字符串（每行一个 todo）。
        priority_map: task title → priority 覆盖映射。

    Returns:
        TodoItem 列表，id 自动生成。

    Example:
        >>> todos = plan_to_todos([{"title": "Write tests", "description": "..."}])
        >>> todos[0].content
        'Write tests'
        >>> todos[0].status
        'pending'
    """
    pm = priority_map or {}
    todos: list[TodoItem] = []

    if isinstance(plan, str):
        for line in plan.strip().splitlines():
            line = line.strip().lstrip("-*•123456789. ")
            if not line:
                continue
            tid = f"todo_{uuid.uuid4().hex[:8]}"
            todos.append(
                TodoItem(
                    id=tid,
                    content=line,
                    status="pending",
                    priority=pm.get(line, "medium"),
                )
            )
        return todos

    for item in plan:
        if isinstance(item, dict):
            title = item.get("title") or item.get("content", "")
            tid = item.get("id") or f"todo_{uuid.uuid4().hex[:8]}"
            todos.append(
                TodoItem(
                    id=tid,
                    content=title,
                    status=item.get("status", "pending"),
                    priority=pm.get(title, item.get("priority", "medium")),
                )
            )
    return todos
