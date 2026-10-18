"""Local hybrid search: BM25 (tantivy) + dense vector (lancedb) fused with RRF."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC
from typing import Any, Literal, Protocol

from oprim._logging import log
from oprim.embedding import embed_text
from oprim.fulltext import open_fulltext_index
from oprim.meta_db import open_meta_db
from oprim.vector_db import open_vector_db

from oskill._exceptions import OskillError
from oskill.knowledge._context import lancedb_path, meta_db_path, tantivy_path

_VECTOR_DIM = 1024
_TABLE_NAME = "vectors_text"
_RRF_K = 60


class Reranker(Protocol):
    def __call__(
        self, *, query: str, documents: list[str], top_k: int | None = None
    ) -> list[Any]: ...


class QueryExpander(Protocol):
    def __call__(self, *, query: str, num_variants: int) -> list[str]: ...


@dataclass
class SearchResult:
    type: str
    id: str
    title: str
    score: float
    highlight: str | None
    metadata: dict = field(default_factory=dict)
    citation: dict | None = None


@dataclass
class HybridSearchResult:
    results: list[SearchResult]
    query: str
    corpus_id: str | None
    total: int


async def hybrid_search(
    query: str,
    *,
    corpus_id: str | None = None,
    top_k: int = 10,
    mode: Literal["strict", "augmented"] = "augmented",
    pinned_boost: float = 1.5,
    rerank: Reranker | None = None,
    rerank_top_k: int | None = None,
    expand: QueryExpander | None = None,
    expand_num_variants: int = 3,
    return_citations: bool = True,
    view_id: str | None = None,
    filter_medium: list[str] | None = None,
    filter_tags: list[str] | None = None,
) -> list[SearchResult]:
    """Hybrid search: BM25 + dense vector + RRF fusion.

    Args:
        query: Query string.
        corpus_id: Knowledge corpus ID.
        top_k: Number of results.
        mode: "strict" — substrate hits only, no LLM.
              "augmented" — substrate + LLM general knowledge fallback on zero hits.
        pinned_boost: Multiply score of is_pinned substrates by this factor (re-sorts).
        rerank: Reranker function.
        rerank_top_k: Truncation before reranking.
        expand: Query expansion function.
        expand_num_variants: Number of variants to generate.
        return_citations: Populate citation field on each result.
        view_id: Apply this view's default_filter.
        filter_medium: Restrict results to these medium types.
        filter_tags: Restrict results to these domain tags.
    """
    if not query or not query.strip():
        raise OskillError("Query cannot be empty")
    if corpus_id is None:
        raise OskillError("hybrid_search: corpus_id is required")
    if not corpus_id.strip():
        raise OskillError("corpus_id cannot be empty")

    queries = [query]
    if expand:
        expanded = expand(query=query, num_variants=expand_num_variants)
        if expanded:
            queries = expanded

    # Phase 13: resolve view filter
    time_range = None
    if view_id is not None:
        vf = _load_view_filter(view_id)
        if vf:
            if filter_medium is None and vf.get("medium"):
                filter_medium = list(vf["medium"])
            if filter_tags is None and vf.get("domain"):
                filter_tags = list(vf["domain"])
            if time_range is None and vf.get("time_range"):
                time_range = vf["time_range"]

    all_bm25 = []
    all_dense = []

    for q in queries:
        all_bm25.extend(_bm25_search(q, top_k * 2))
        all_dense.extend(await _dense_search(q, top_k * 2))

    fused = _rrf_fuse(all_bm25, all_dense, k=_RRF_K, top_k=top_k * 2)

    if pinned_boost != 1.0 and fused:
        fused = _boost_pinned(fused, pinned_boost)

    enriched = _enrich(fused, return_citations=return_citations)
    filtered = _apply_filters(enriched, filter_medium, filter_tags, None, time_range)

    if rerank and filtered:
        to_rerank = filtered[:rerank_top_k] if rerank_top_k else filtered
        docs_text = [r.title + "\n" + (r.highlight or "") for r in to_rerank]
        reranked_scores = rerank(query=query, documents=docs_text, top_k=top_k)

        reranked_filtered = []
        for r_res in reranked_scores:
            idx = r_res.original_index
            if 0 <= idx < len(to_rerank):
                doc = to_rerank[idx]
                doc.score = r_res.score
                reranked_filtered.append(doc)
        filtered = reranked_filtered

    if mode == "augmented" and not filtered:
        filtered = await _llm_augmented(query)

    log.info(
        "oskill.hybrid_search.done",
        query=query[:80],
        mode=mode,
        view_id=view_id,
        corpus_id=corpus_id,
        results=len(filtered[:top_k]),
    )
    return filtered[:top_k]


# ── View filter resolution (reads views table directly — no omodul dep) ──────


def _load_view_filter(view_id: str | None) -> dict:
    """Return the default_filter dict for the given view."""
    db_p = meta_db_path()
    if not db_p.exists() or not view_id:
        return {}
    try:
        db = open_meta_db(db_p)
        rows = db.fetchall("SELECT default_filter FROM views WHERE id = ?", [view_id])
        db.close()
        if not rows or not rows[0][0]:
            return {}
        return json.loads(rows[0][0]) or {}
    except Exception as e:
        log.warning("oskill.hybrid_search.view_load_error", error=str(e))
        return {}


# ── BM25 ──────────────────────────────────────────────────────────────────────


def _bm25_search(query: str, top_k: int) -> list[tuple[str, float]]:
    idx_path = tantivy_path()
    if not idx_path.exists():
        return []
    try:
        idx = open_fulltext_index(idx_path)
        hits = idx.search(query, top_k=top_k)
        return [(h.id, h.score) for h in hits]
    except Exception as e:
        log.warning("oskill.hybrid_search.bm25_error", error=str(e))
        return []


# ── Dense vector ──────────────────────────────────────────────────────────────


async def _dense_search(query: str, top_k: int) -> list[tuple[str, float]]:
    db_path = lancedb_path()
    if not db_path.exists():
        return []
    try:
        from oprim._config import cfg

        provider = str(cfg.get("EMBEDDING_PROVIDER", "qwen3_dashscope"))
        vecs = embed_text([query], provider=provider, dim=_VECTOR_DIM)
        vdb = open_vector_db(db_path, table_name=_TABLE_NAME, dim=_VECTOR_DIM)
        records = vdb.search(vecs[0], top_k=top_k)
        results = []
        for r in records:
            sub_id = r.id.split("#")[0]
            score = r.metadata.get("_distance", 0.0)
            results.append((sub_id, 1.0 / (1.0 + float(score))))
        return results
    except Exception as e:
        log.warning("oskill.hybrid_search.dense_error", error=str(e))
        return []


# ── RRF ───────────────────────────────────────────────────────────────────────


def _rrf_fuse(
    list_a: list[tuple[str, float]],
    list_b: list[tuple[str, float]],
    k: int = 60,
    top_k: int = 20,
) -> list[tuple[str, float]]:
    """Reciprocal Rank Fusion of two ranked lists."""
    scores: dict[str, float] = {}
    for rank, (item_id, _) in enumerate(list_a):
        scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (k + rank + 1)
    for rank, (item_id, _) in enumerate(list_b):
        scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_k]


# ── Pinned boost ──────────────────────────────────────────────────────────────


def _boost_pinned(
    fused: list[tuple[str, float]],
    boost: float,
) -> list[tuple[str, float]]:
    """Multiply score of is_pinned substrates, then re-sort."""
    pinned = _get_pinned_ids([sid for sid, _ in fused])
    boosted = [(sid, score * boost if sid in pinned else score) for sid, score in fused]
    return sorted(boosted, key=lambda x: x[1], reverse=True)


def _get_pinned_ids(substrate_ids: list[str]) -> set[str]:
    db_p = meta_db_path()
    if not db_p.exists() or not substrate_ids:
        return set()
    try:
        db = open_meta_db(db_p)
        ph = ",".join("?" * len(substrate_ids))
        rows = db.fetchall(
            f"SELECT id FROM substrates WHERE id IN ({ph}) AND is_pinned = true",
            substrate_ids,
        )
        db.close()
        return {r[0] for r in rows}
    except Exception as e:
        log.warning("oskill.hybrid_search.get_pinned_error", error=str(e))
        return set()


# ── Enrich ────────────────────────────────────────────────────────────────────


def _enrich(fused: list[tuple[str, float]], return_citations: bool = True) -> list[SearchResult]:
    """Fetch substrate metadata from DuckDB and build SearchResult list."""
    if not fused:
        return []
    db_p = meta_db_path()
    if not db_p.exists():
        return [
            SearchResult(
                type="substrate",
                id=sid,
                title=sid,
                score=sc,
                highlight=None,
                citation=_make_citation(sid, return_citations),
            )
            for sid, sc in fused
        ]
    try:
        db = open_meta_db(db_p)
        id_list = [sid for sid, _ in fused]
        placeholders = ",".join("?" * len(id_list))
        rows = db.fetchall(
            f"SELECT id, title, meta_json, created_at FROM substrates WHERE id IN ({placeholders})",
            id_list,
        )
        db.close()
        meta_map = {r[0]: r for r in rows}
    except Exception as e:
        log.warning("oskill.hybrid_search.enrich_error", error=str(e))
        meta_map = {}

    results = []
    for sid, score in fused:
        row = meta_map.get(sid)
        if row:
            try:
                meta = json.loads(row[2]) if row[2] else {}
            except Exception:
                meta = {}
            results.append(
                SearchResult(
                    type="substrate",
                    id=sid,
                    title=row[1] or sid,
                    score=score,
                    highlight=None,
                    metadata={
                        "medium": meta.get("medium"),
                        "source_type": meta.get("source_type"),
                        "domain": meta.get("domain"),
                        "created_at": str(row[3]) if row[3] else None,
                    },
                    citation=_make_citation(sid, return_citations),
                )
            )
        else:
            results.append(
                SearchResult(
                    type="substrate",
                    id=sid,
                    title=sid,
                    score=score,
                    highlight=None,
                    citation=_make_citation(sid, return_citations),
                )
            )
    return results


def _make_citation(substrate_id: str, return_citations: bool) -> dict | None:
    if not return_citations:
        return None
    fragment_id = f"{substrate_id}#0"
    return {
        "substrate_id": substrate_id,
        "fragment_id": fragment_id,
        "anchor": {"section": None, "char_start": 0, "char_end": 0},
        "deep_link": f"stratum://substrate/{substrate_id}/#{fragment_id}",
    }


# ── Filters ───────────────────────────────────────────────────────────────────


def _apply_filters(
    results: list[SearchResult],
    medium_filter: list[str] | None,
    domain_filter: list[str] | None,
    type_filter: list[str] | None,
    time_range: str | None = None,
) -> list[SearchResult]:
    if type_filter:
        results = [r for r in results if r.type in type_filter]
    if medium_filter:
        results = [r for r in results if r.metadata.get("medium") in medium_filter]
    if domain_filter:
        results = [
            r
            for r in results
            if r.metadata.get("domain") is None or r.metadata["domain"] in domain_filter
        ]
    if time_range:
        results = _apply_time_range(results, time_range)
    return results


_TIME_RANGE_DELTAS = {
    "last_24h": 1,
    "last_7d": 7,
    "last_30d": 30,
    "last_90d": 90,
}


def _apply_time_range(results: list[SearchResult], time_range: str) -> list[SearchResult]:
    """Filter results by created_at against a named time window."""
    from datetime import datetime, timedelta

    days = _TIME_RANGE_DELTAS.get(time_range)
    if days is None:
        log.warning("oskill.hybrid_search.unknown_time_range", time_range=time_range)
        return results
    cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
    return [
        r
        for r in results
        if r.metadata.get("created_at") is None or str(r.metadata["created_at"]) >= cutoff
    ]


# ── LLM augmented fallback (mode=augmented, zero substrate hits) ──────────────


async def _llm_augmented(query: str) -> list[SearchResult]:
    try:
        from oprim.llm import llm_call

        response = await llm_call(
            prompt=f"Answer briefly based on your knowledge: {query}",
            provider="qwen3_dashscope",
        )
        return [
            SearchResult(
                type="llm_augmented",
                id="llm-augmented-0",
                title="General Knowledge",
                score=0.5,
                highlight=str(response)[:500],
                metadata={"source": "llm_augmented"},
                citation=None,
            )
        ]
    except Exception as e:
        log.warning("oskill.hybrid_search.llm_augment_failed", error=str(e))
        return []
