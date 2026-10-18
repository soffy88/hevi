"""Auto-split from hicode whl."""

from __future__ import annotations
from oprim import count_tokens, embed_text

from typing import Any, Protocol, runtime_checkable


from ._types import Chunk, LLMOskillError


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


async def semantic_search(
    query: str,
    *,
    store: VectorStoreHandle,
    embed_caller: Any,
    top_k: int = 5,
    filter: dict | None = None,
) -> list[Chunk]:
    """语义向量搜索，返回最相关的代码 Chunk 列表。

    组合：embed_text(oprim C批) + store.search(VectorStoreHandle Protocol)。
    oskill 约束：只读，不写盘。

    Args:
        query: 自然语言查询。
        store: VectorStoreHandle Protocol 实例（由调用方注入）。
        embed_caller: EmbedCaller Protocol 实例（用于 embed query）。
        top_k: 返回数量，默认 5。
        filter: 向量检索过滤条件（可选，传给 store）。

    Returns:
        Chunk 列表（按相似度排序）。

    Raises:
        LLMOskillError: 嵌入或检索失败。

    Example:
        >>> chunks = await semantic_search("user authentication", store=vs, embed_caller=ec)
        >>> chunks[0].content
        'def authenticate_user(...):'
    """
    if not query or not query.strip():
        raise LLMOskillError("semantic_search: query must not be empty")

    # embed query（复用 oprim embed_text 的逻辑，直接调 embed_caller）
    try:
        vector = await embed_caller(text=query, model="text-embedding-3-small")
    except Exception as e:
        raise LLMOskillError("semantic_search: embedding failed", cause=e)

    # 向量检索
    try:
        raw = await store.search(vector=vector, top_k=top_k, filter=filter)
    except Exception as e:
        raise LLMOskillError("semantic_search: vector store search failed", cause=e)

    chunks: list[Chunk] = []
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        chunks.append(
            Chunk(
                content=item.get("content", ""),
                start_line=item.get("start_line", 0),
                end_line=item.get("end_line", 0),
                token_count=item.get("token_count", count_tokens(item.get("content", ""))),
                path=item.get("path", ""),
                language=item.get("language", ""),
                chunk_id=item.get("chunk_id", ""),
            )
        )

    return chunks
