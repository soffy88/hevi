"""Auto-split from hicode whl."""

from __future__ import annotations
from oprim import count_tokens

from typing import Any, Protocol, runtime_checkable


from ._types import LLMOskillError


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


async def compress_context(
    messages: list[dict],
    *,
    caller: Any,
    budget: int = 4000,
    model: str = "claude-sonnet-4-6",
) -> list[dict]:
    """将过长的消息历史压缩为摘要，返回新的消息列表（LLM 辅助）。

    组合：count_tokens(oprim) + caller(LLMCaller Protocol)。
    若已在预算内，直接返回原列表（不调 LLM）。

    Args:
        messages: 当前消息列表。
        caller: LLMCaller Protocol 实例。
        budget: 目标 token 预算，默认 4000。
        model: 用于 token 计数的模型名。

    Returns:
        压缩后的消息列表（首条保留，中间替换为摘要，末 2 条保留）。

    Raises:
        LLMOskillError: LLM 调用失败。

    Example:
        >>> short = await compress_context(long_messages, caller=my_caller, budget=2000)
        >>> count_tokens(short) <= 2000 * 1.2  # 允许 20% 余量
        True
    """
    if not messages:
        return []

    current_tokens = count_tokens(messages, model=model)
    if current_tokens <= budget:
        return list(messages)

    # 保留首 1 条（system/user）和末 2 条（最近上下文）
    keep_first = messages[:1]
    keep_last = messages[-2:] if len(messages) > 3 else []
    middle = messages[1 : len(messages) - len(keep_last)] if keep_last else messages[1:]

    if not middle:
        return list(messages)  # pragma: no cover

    # 用 LLM 压缩 middle 部分
    history_text = "\n".join(f"[{m.get('role', '?')}]: {_msg_text(m)[:500]}" for m in middle)
    compress_prompt = (
        f"Summarize this conversation history in 3-5 sentences, "
        f"preserving key decisions, code changes, and findings:\n\n{history_text}"
    )

    try:
        response = await caller(
            messages=[{"role": "user", "content": compress_prompt}],
            tools=None,
            max_tokens=512,
        )
        summary_text = ""
        for block in response.get("content", []):
            if isinstance(block, dict) and block.get("type") == "text":
                summary_text += block.get("text", "")
        summary_text = summary_text.strip() or "(conversation history)"
    except Exception as e:
        raise LLMOskillError("compress_context: LLM call failed", cause=e)

    summary_msg = {"role": "user", "content": f"[Conversation summary]: {summary_text}"}
    return keep_first + [summary_msg] + keep_last


def _msg_text(msg: dict) -> str:
    content = msg.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"
        )
    return str(content)
