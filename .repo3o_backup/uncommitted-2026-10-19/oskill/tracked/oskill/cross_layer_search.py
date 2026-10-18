"""Cross-layer search fusing platform content, user substrate, and notes via RRF."""

from __future__ import annotations

import time
from datetime import date
from typing import Any, Protocol

from pydantic import BaseModel

from oskill._exceptions import OskillError


class Citation(BaseModel):
    id: str
    title: str
    source: str
    url: str | None = None


class FusedResult(BaseModel):
    id: str
    type: str  # "platform_content" | "user_substrate" | "user_note" | "concept"
    title: str
    score: float  # RRF fused score
    highlight: str
    citation: Citation
    source: str  # which index it came from
    user_id: str | None = None  # owner (set by user-scoped managers; None = shared)


class CrossLayerSearchResult(BaseModel):
    results: list[FusedResult]
    citations: list[Citation]
    search_time_ms: int
    scope_hit_counts: dict[str, int]


# Protocols for injected managers
class TantivyMgr(Protocol):
    def __call__(
        self,
        *,
        query: str,
        top_k: int,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]: ...


class LanceDBMgr(Protocol):
    def __call__(
        self,
        *,
        query_embedding: list[float] | None,
        query: str,
        top_k: int,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]: ...


class PGVectorMgr(Protocol):
    def __call__(
        self,
        *,
        query_embedding: list[float] | None,
        top_k: int,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]: ...


_RRF_K = 60
_DEFAULT_SCOPE = ["platform_content", "user_substrate", "user_notes", "concept"]


def cross_layer_search(
    *,
    query: str,
    query_embedding: list[float] | None = None,
    scope: list[str] | None = None,
    mode: str = "augmented",
    top_k: int = 20,
    pinned_boost: float = 1.5,
    medium_filter: list[str] | None = None,
    domain_filter: list[str] | None = None,
    date_range: tuple[date, date] | None = None,
    tantivy_mgr: TantivyMgr,
    lancedb_mgr: LanceDBMgr,
    pgvector_mgr: PGVectorMgr | None = None,
) -> CrossLayerSearchResult:
    """Cross-index search fusing platform content, user substrate, and notes.

    Internal oskill composition:
        - tantivy_mgr: full-text search (injected, implements TantivyMgr protocol)
        - lancedb_mgr: vector search on user data (injected, implements LanceDBMgr protocol)
        - pgvector_mgr: platform content vector search (optional, injected)
        - RRF fusion algorithm with pinned_boost (pure algorithm)

    Args:
        query: Search query string
        query_embedding: Pre-computed query embedding (optional, for vector search)
        scope: Which indices to search. Default all: ["platform_content", "user_substrate",
            "user_notes", "concept"]
        mode: "augmented" | "strict"
        top_k: Number of results to return
        pinned_boost: Score multiplier for user items where is_pinned=True
        medium_filter: Filter by medium type (e.g. ["pdf", "epub"])
        domain_filter: Filter by domain/tag
        date_range: (start, end) date filter
        tantivy_mgr: Injected full-text search callable
        lancedb_mgr: Injected user vector store callable
        pgvector_mgr: Injected platform vector store callable (None -> skip platform)

    Returns:
        CrossLayerSearchResult with fused results and citations

    Raises:
        OskillError: Empty query

    Example:
        >>> result = cross_layer_search(
        ...     query="machine learning",
        ...     tantivy_mgr=mock_tantivy,
        ...     lancedb_mgr=mock_lancedb,
        ... )
        >>> isinstance(result.results, list)
        True
    """
    if not query.strip():
        raise OskillError("cross_layer_search: query cannot be empty")

    if scope is None:
        scope = _DEFAULT_SCOPE

    t_start = time.monotonic()

    filters: dict[str, Any] = {}
    if medium_filter:
        filters["medium"] = medium_filter
    if domain_filter:
        filters["domain"] = domain_filter
    if date_range:
        filters["date_range"] = [date_range[0].isoformat(), date_range[1].isoformat()]

    raw_results: dict[str, list[dict[str, Any]]] = {}
    scope_hit_counts: dict[str, int] = {}

    # Full-text search (tantivy) covers user_substrate, user_notes, concept
    user_scopes = [s for s in scope if s != "platform_content"]
    if user_scopes:
        try:
            hits = tantivy_mgr(query=query, top_k=top_k, filters=filters or None)
            raw_results["tantivy"] = hits
            # Attribute hits to scope by type field
            for s in user_scopes:
                scope_hit_counts[s] = sum(1 for h in hits if h.get("type", "") == s)
        except Exception:
            raw_results["tantivy"] = []

    # Platform content vector search (pgvector, optional)
    if "platform_content" in scope:
        if pgvector_mgr is not None:
            try:
                hits = pgvector_mgr(
                    query_embedding=query_embedding, top_k=top_k, filters=filters or None
                )
                raw_results["pgvector"] = hits
                scope_hit_counts["platform_content"] = len(hits)
            except Exception:
                raw_results["pgvector"] = []
        else:
            scope_hit_counts["platform_content"] = 0

    # User vector search (lancedb)
    if user_scopes:
        try:
            vec_hits = lancedb_mgr(
                query_embedding=query_embedding,
                query=query,
                top_k=top_k,
                filters=filters or None,
            )
            raw_results["lancedb"] = vec_hits
        except Exception:
            raw_results["lancedb"] = []

    # RRF fusion
    rrf_scores: dict[str, float] = {}
    item_registry: dict[str, dict[str, Any]] = {}

    for source_name, hits in raw_results.items():
        for rank, hit in enumerate(hits):
            hit_id: str = str(hit.get("id", f"{source_name}-{rank}"))
            rrf_score: float = 1.0 / (_RRF_K + rank + 1)
            if hit.get("is_pinned"):
                rrf_score *= pinned_boost
            rrf_scores[hit_id] = rrf_scores.get(hit_id, 0.0) + rrf_score
            if hit_id not in item_registry:
                hit["_source"] = source_name
                item_registry[hit_id] = hit

    sorted_ids = sorted(rrf_scores, key=lambda x: rrf_scores[x], reverse=True)[:top_k]

    fused: list[FusedResult] = []
    for fid in sorted_ids:
        item = item_registry[fid]
        cit = Citation(
            id=fid,
            title=item.get("title", fid),
            source=item.get("_source", "unknown"),
            url=item.get("url"),
        )
        fused.append(
            FusedResult(
                id=fid,
                type=item.get("type", "unknown"),
                title=item.get("title", fid),
                score=rrf_scores[fid],
                highlight=item.get("highlight", item.get("excerpt", "")),
                citation=cit,
                source=item.get("_source", "unknown"),
                user_id=item.get("user_id"),
            )
        )

    elapsed_ms = int((time.monotonic() - t_start) * 1000)

    return CrossLayerSearchResult(
        results=fused,
        citations=[r.citation for r in fused],
        search_time_ms=elapsed_ms,
        scope_hit_counts=scope_hit_counts,
    )
