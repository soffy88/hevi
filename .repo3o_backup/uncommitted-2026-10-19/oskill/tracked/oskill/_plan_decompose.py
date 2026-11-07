"""Auto-split from hicode whl."""

from __future__ import annotations

import json
import re
from typing import Any, Protocol, runtime_checkable

from ._types import LLMOskillError, SubTask


@runtime_checkable
class VectorStoreHandle(Protocol):
    """
    向量存储 Protocol（obase.persistence 向量查询接口）。
    semantic_search 接受此类型注入，不 import obase.persistence。
    生产实现由 obase.persistence.VectorStore 提供。
    """

    async def search(
        self, *, vector: list[float], top_k: int = 5, filter: dict | None = None
    ) -> list[dict[str, Any]]:
        """
        向量相似度搜索。

        Returns:
            list of {"chunk_id": str, "content": str, "score": float, "path": str}
        """
        ...


async def plan_decompose(
    goal: str,
    *,
    caller: Any,
    context: str = "",
    max_subtasks: int = 10,
) -> list[SubTask]:
    """将高层目标分解为有序子任务列表（LLM 辅助）。

    组合：prompt 构建(纯) + caller(LLMCaller Protocol) + JSON 解析(纯)。

    Args:
        goal: 高层任务描述。
        caller: LLMCaller Protocol 实例。
        context: 额外上下文（如代码库信息），可选。
        max_subtasks: 最多子任务数，默认 10。

    Returns:
        SubTask 列表（有序，含依赖关系）。

    Raises:
        LLMOskillError: LLM 调用失败或响应无法解析。

    Example:
        >>> tasks = await plan_decompose("Add user auth", caller=my_caller)
        >>> tasks[0].title
        'Design auth schema'
    """
    ctx_section = f"\n\nContext:\n{context}" if context else ""
    prompt = (
        f"Decompose this goal into {max_subtasks} or fewer concrete subtasks. "
        f"Return ONLY a JSON array of objects with fields: "
        f"id (string), title (string), description (string), "
        f"dependencies (array of ids), estimated_complexity (low/medium/high).\n\n"
        f"Goal: {goal}{ctx_section}"
    )

    try:
        response = await caller(
            messages=[{"role": "user", "content": prompt}],
            tools=None,
            max_tokens=1024,
        )
        raw_text = ""
        for block in response.get("content", []):
            if isinstance(block, dict) and block.get("type") == "text":
                raw_text += block.get("text", "")
    except Exception as e:
        raise LLMOskillError("plan_decompose: LLM call failed", cause=e)

    # 解析 JSON
    raw_text = raw_text.strip()
    # 去除 markdown fence
    raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text, flags=re.MULTILINE)
    raw_text = re.sub(r"```\s*$", "", raw_text, flags=re.MULTILINE)

    try:
        items = json.loads(raw_text.strip())
        if not isinstance(items, list):
            items = []  # pragma: no cover
    except (json.JSONDecodeError, ValueError):
        # 回退：尝试提取 JSON 数组
        m = re.search(r"\[.*\]", raw_text, re.DOTALL)
        if m:
            try:  # pragma: no cover
                items = json.loads(m.group(0))  # pragma: no cover
            except Exception:  # pragma: no cover
                items = []  # pragma: no cover
        else:
            items = []

    subtasks: list[SubTask] = []
    for item in items[:max_subtasks]:
        if not isinstance(item, dict):
            continue  # pragma: no cover
        subtasks.append(
            SubTask(
                id=str(item.get("id", f"task_{len(subtasks) + 1}")),
                title=str(item.get("title", "")),
                description=str(item.get("description", "")),
                dependencies=[str(d) for d in item.get("dependencies", [])],
                estimated_complexity=str(item.get("estimated_complexity", "medium")),
            )
        )

    return subtasks
