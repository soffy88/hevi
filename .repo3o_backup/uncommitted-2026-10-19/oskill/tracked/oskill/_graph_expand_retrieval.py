"""K-G4: graph_expand_retrieval — BFS graph expansion with relevance pruning.

Composition:
  - relevance_fn (K-G3 relevance_compute, injected)
  - db_conn (graph store, injected)

BFS from seed KUs, expanding up to max_hops, scoring by relevance,
returning top max_results sorted by score descending.

db_conn expected interface:
  get_neighbors(ku_id: str) -> list[str]          (async or sync)
  get_ku_data(ku_id: str) -> dict                  (async or sync)
    → {sources, type, neighbors, edges}
"""

from __future__ import annotations

import inspect
from collections import deque
from collections.abc import Callable
from typing import Any

from oprim._aii_graph_types import GraphRetrievalResult


async def graph_expand_retrieval(
    *,
    seed_ku_ids: list[str],
    query_embedding: list[float],
    max_hops: int = 2,
    max_results: int = 20,
    db_conn: Any,
    relevance_fn: Callable,
) -> list[GraphRetrievalResult]:
    """BFS graph retrieval expanding from seed KUs.

    Composition: relevance_fn (K-G3, injected), db_conn (injected).
    Handles cycles via visited set. Returns top max_results by score.
    """
    if not seed_ku_ids:
        return []

    visited: set[str] = set(seed_ku_ids)
    results: list[GraphRetrievalResult] = []

    # BFS queue: (ku_id, hop_distance, path_from_seed)
    queue: deque[tuple[str, int, list[str]]] = deque()
    for seed in seed_ku_ids:
        queue.append((seed, 0, [seed]))

    while queue:
        ku_id, hop, path = queue.popleft()

        if hop > max_hops:
            continue

        # Skip seeds themselves (hop=0); they are the starting points
        if hop > 0:
            # Compute relevance against the first seed
            seed_id = path[0]
            score = await _compute_relevance(
                ku_id_a=seed_id,
                ku_id_b=ku_id,
                db_conn=db_conn,
                relevance_fn=relevance_fn,
            )
            results.append(
                GraphRetrievalResult(
                    ku_id=ku_id,
                    score=score,
                    hop_distance=hop,
                    retrieval_path=list(path),
                )
            )

        if hop < max_hops:
            neighbors = await _get_neighbors(db_conn, ku_id)
            for neighbor in neighbors:
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, hop + 1, path + [neighbor]))

    # Sort by score descending, truncate to max_results
    results.sort(key=lambda r: r.score, reverse=True)
    return results[:max_results]


async def _get_neighbors(db_conn: Any, ku_id: str) -> list[str]:
    try:
        fn = db_conn.get_neighbors
        if inspect.iscoroutinefunction(fn):
            return list(await fn(ku_id))
        return list(fn(ku_id))
    except Exception:
        return []


async def _get_ku_data(db_conn: Any, ku_id: str) -> dict:
    try:
        fn = db_conn.get_ku_data
        if inspect.iscoroutinefunction(fn):
            return dict(await fn(ku_id)) or {}
        return dict(fn(ku_id)) or {}
    except Exception:
        return {}


async def _compute_relevance(
    *, ku_id_a: str, ku_id_b: str, db_conn: Any, relevance_fn: Callable
) -> float:
    data_a = await _get_ku_data(db_conn, ku_id_a)
    data_b = await _get_ku_data(db_conn, ku_id_b)
    edges = data_a.get("edges", []) + data_b.get("edges", [])
    try:
        score = relevance_fn(
            ku_id_a=ku_id_a,
            ku_id_b=ku_id_b,
            edges=edges,
            sources_a=data_a.get("sources", []),
            sources_b=data_b.get("sources", []),
            neighbors_a=data_a.get("neighbors", []),
            neighbors_b=data_b.get("neighbors", []),
            neighbor_degree=data_a.get("neighbor_degree", {}),
            type_a=data_a.get("type", "unknown"),
            type_b=data_b.get("type", "unknown"),
        )
        return float(score)
    except Exception:
        return 0.0
