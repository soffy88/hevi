"""oskill.hybrid_retrieve — multi-signal hybrid retrieval with RRF fusion.

3O layer: oskill (≥2 oprim composition, stateless, no persistence).

Internal oprim composition:
    - oprim.bm25_search: keyword/BM25 retrieval signal
    - oprim.entity_graph_search: graph-traversal retrieval signal
    (oprim.vector_encode available for dense signal when provider configured)

RRF (Reciprocal Rank Fusion) merges ranked lists from multiple signals.
Precise identifier matching (ADR-038) via BM25 complements graph traversal.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable

from oprim import bm25_search, entity_graph_search


def hybrid_retrieve(
    *,
    query: str,
    docs: dict[str, str],
    seed_ids: list[str],
    list_edges: Callable,
    top_k: int = 10,
    rrf_k: int = 60,
) -> list[tuple[str, float]]:
    """Multi-signal hybrid retrieval using RRF fusion.

    Returns [(doc_id, rrf_score)] sorted descending.

    Args:
        query: Search query string for BM25 signal.
        docs: {doc_id: text} corpus for BM25 keyword retrieval.
        seed_ids: Starting node IDs for graph traversal signal.
        list_edges: callable(node_id) -> list of edge objects with .dst_id attribute.
        top_k: Maximum number of results to return.
        rrf_k: RRF smoothing constant (default 60).

    Internal oprim composition:
        bm25_search provides keyword/identifier matching signal.
        entity_graph_search provides graph-traversal structural signal.
        RRF fuses both ranked lists: score(id) = sum(1 / (rrf_k + rank)).
    """
    # 1. BM25 signal via oprim.bm25_search
    bm25_results = bm25_search(query=query, docs=docs, top_k=top_k * 2)

    # 2. Graph signal via oprim.entity_graph_search
    graph_results: list[tuple[str, float]] = []
    if seed_ids:
        graph_results = entity_graph_search(
            seed_ids=seed_ids, list_edges=list_edges, hops=2, top_k=top_k * 2
        )

    # 3. RRF fusion — inline from merge_platform_user_results RRF logic
    fused: dict[str, float] = defaultdict(float)
    for ranked_list in (bm25_results, graph_results):
        for rank, (doc_id, _score) in enumerate(ranked_list):
            fused[doc_id] += 1.0 / (rrf_k + rank)

    sorted_fused = sorted(fused.items(), key=lambda x: -x[1])
    return sorted_fused[:top_k]
