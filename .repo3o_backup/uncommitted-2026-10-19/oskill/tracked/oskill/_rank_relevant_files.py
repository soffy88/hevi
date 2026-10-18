"""Auto-split from hicode whl."""

from __future__ import annotations

import re
from typing import Any, Protocol, runtime_checkable

from ._types import RepoMap


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


async def rank_relevant_files(
    query: str,
    *,
    repo_map: RepoMap,
    caller: Any | None = None,
    top_k: int = 10,
) -> list[tuple[str, float]]:
    """对 repo_map 中的文件按与 query 的相关度排序（纯内存 + 可选 LLM）。

    无 LLM 时：关键词 + 符号名匹配评分。
    有 LLM（caller 非 None）：用 LLM 对 top 候选做 rerank（未来扩展点，
    当前实现仅关键词模式，caller 参数保留接口）。

    Args:
        query: 搜索查询。
        repo_map: build_repo_context 产出的 RepoMap。
        caller: LLMCaller Protocol（可选，当前未使用）。
        top_k: 返回文件数，默认 10。

    Returns:
        list of (path, score) 元组，按 score 降序。

    Example:
        >>> ranked = await rank_relevant_files("authentication", repo_map=rmap)
        >>> ranked[0][1] > 0
        True
    """
    query_words = set(re.findall(r"\w+", query.lower()))

    scored: list[tuple[str, float]] = []
    for rf in repo_map.files:
        path_words = set(re.findall(r"\w+", rf.path.lower()))
        sym_words = set(
            w
            for sym in rf.symbols
            for w in re.findall(r"\w+", (sym.name + " " + sym.signature).lower())
        )
        head_words = set(re.findall(r"\w+", rf.head_lines.lower()))
        all_words = path_words | sym_words | head_words

        overlap = len(query_words & all_words)
        # 加权：符号名命中权重 > 路径 > head
        sym_hit = len(query_words & sym_words)
        path_hit = len(query_words & path_words)
        score = (sym_hit * 3 + path_hit * 2 + overlap) / max(len(query_words) * 3, 1)
        if score > 0:
            scored.append((rf.path, round(score, 4)))

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top_k]
