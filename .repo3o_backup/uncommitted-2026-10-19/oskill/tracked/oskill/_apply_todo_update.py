"""Auto-split from hicode whl."""

from __future__ import annotations

from dataclasses import dataclass

from ._types import (
    OskillError,
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


def apply_todo_update(
    todos: list[TodoItem],
    *,
    todo_id: str,
    status: str | None = None,
    content: str | None = None,
    priority: str | None = None,
) -> list[TodoItem]:
    """更新单个 todo 的状态/内容/优先级（纯内存状态机）。

    Args:
        todos: 当前 TodoItem 列表。
        todo_id: 要更新的 todo id。
        status: 新状态（可选）。
        content: 新内容（可选）。
        priority: 新优先级（可选）。

    Returns:
        更新后的 TodoItem 列表（不可变风格：返回新列表）。

    Raises:
        OskillError: todo_id 不存在或状态值不合法。

    Example:
        >>> updated = apply_todo_update(todos, todo_id="t1", status="done")
        >>> next(t for t in updated if t.id == "t1").status
        'done'
    """
    VALID_STATUSES = {"pending", "in_progress", "done", "cancelled"}
    VALID_PRIORITIES = {"high", "medium", "low"}

    if status and status not in VALID_STATUSES:
        raise OskillError(f"invalid status '{status}': must be one of {VALID_STATUSES}")
    if priority and priority not in VALID_PRIORITIES:
        raise OskillError(f"invalid priority '{priority}': must be one of {VALID_PRIORITIES}")

    updated = []
    found = False
    for todo in todos:
        if todo.id == todo_id:
            found = True
            updated.append(
                TodoItem(
                    id=todo.id,
                    content=content if content is not None else todo.content,
                    status=status if status is not None else todo.status,
                    priority=priority if priority is not None else todo.priority,
                )
            )
        else:
            updated.append(todo)

    if not found:
        raise OskillError(f"todo_id '{todo_id}' not found")
    return updated
