"""Auto-split from hicode whl."""

from __future__ import annotations
from oprim import count_tokens, file_read

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


async def summarize_file(
    path: str,
    *,
    caller: Any,
    max_content_tokens: int = 8000,
    model: str = "claude-sonnet-4-6",
) -> str:
    """读取文件并用 LLM 生成简洁摘要（文件读 + LLM 调用）。

    组合：file_read(oprim) + count_tokens(oprim) + caller(LLMCaller Protocol)。
    oskill 约束：不写盘，返回摘要字符串。

    Args:
        path: 文件路径。
        caller: LLMCaller Protocol 实例（由调用方注入）。
        max_content_tokens: 输入内容最大 token 数（超出时截断），默认 8000。
        model: 用于 token 计数的模型名。

    Returns:
        文件摘要字符串。

    Raises:
        LLMOskillError: 文件读取或 LLM 调用失败。

    Example:
        >>> summary = await summarize_file("src/main.py", caller=my_caller)
        >>> isinstance(summary, str)
        True
    """
    try:
        content = file_read(path)
    except Exception as e:
        raise LLMOskillError(f"summarize_file: cannot read '{path}'", cause=e)

    # token 预算截断
    toks = count_tokens(content, model=model)
    if toks > max_content_tokens:
        # 粗截断：按比例取前缀
        ratio = max_content_tokens / toks
        content = content[: int(len(content) * ratio)]

    messages = [
        {
            "role": "user",
            "content": (
                f"Summarize this file in 2-4 sentences. Focus on what it does "
                f"and key exported symbols.\n\nFile: {path}\n\n```\n{content}\n```"
            ),
        }
    ]

    try:
        response = await caller(messages=messages, tools=None, max_tokens=256)
        text = ""
        for block in response.get("content", []):
            if isinstance(block, dict) and block.get("type") == "text":
                text += block.get("text", "")
        return text.strip() or "(no summary)"
    except Exception as e:
        raise LLMOskillError(f"summarize_file: LLM call failed for '{path}'", cause=e)
