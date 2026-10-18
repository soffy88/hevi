"""retrieve_runbook — RAG-based runbook retrieval via vector search."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel


class RunbookEntry(BaseModel):
    runbook_id: str
    title: str
    content: str
    score: float
    tags: list[str]


class RetrieveRunbookResult(BaseModel):
    query: str
    results: list[RunbookEntry]
    total_candidates: int


def retrieve_runbook(
    *,
    query: str,
    vector_encode_fn: Callable[[str], list[float]],
    vector_search_fn: Callable[..., list[dict[str, Any]]],
    top_k: int = 5,
    min_score: float = 0.5,
    collection: str = "runbooks",
) -> RetrieveRunbookResult:
    """RAG runbook 检索 — 将查询文本向量化后在 runbook collection 中检索.

    Composition: oprim.vector_encode → oprim.vector_search.
    Designed to feed into synthesize_action_plan as context.

    Args:
        query: 自然语言查询 (e.g. "nginx memory OOM restart")
        vector_encode_fn: oprim.vector_encode callable (text → list[float])
        vector_search_fn: oprim.vector_search callable (vector, collection, top_k → results)
        top_k: 返回最多 N 条结果
        min_score: 最低相似度过滤 (0–1)
        collection: 向量存储 collection 名

    Returns:
        RetrieveRunbookResult
    """
    # Step 1: encode query
    query_vec = vector_encode_fn(query)

    # Step 2: vector search
    raw_results = vector_search_fn(
        vector=query_vec,
        collection=collection,
        top_k=top_k * 2,  # fetch more then filter by min_score
    )

    # Step 3: filter + format
    entries: list[RunbookEntry] = []
    for r in raw_results:
        score = float(r.get("score", 0.0))
        if score < min_score:
            continue
        entries.append(
            RunbookEntry(
                runbook_id=str(r.get("id", r.get("runbook_id", ""))),
                title=str(r.get("title", "")),
                content=str(r.get("content", r.get("text", ""))),
                score=round(score, 4),
                tags=list(r.get("tags", [])),
            )
        )

    entries.sort(key=lambda e: e.score, reverse=True)
    return RetrieveRunbookResult(
        query=query,
        results=entries[:top_k],
        total_candidates=len(raw_results),
    )
