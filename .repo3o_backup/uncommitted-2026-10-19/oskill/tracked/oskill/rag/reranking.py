"""Reranker score — reorder RAG candidates using a reranker function."""

from __future__ import annotations

from collections.abc import Callable


def reranker_score(
    query: str,
    candidates: list[dict],
    reranker_fn: Callable[[str, list[str]], list[float]],
    *,
    top_k: int | None = None,
    score_threshold: float | None = None,
    preserve_original_order_on_ties: bool = True,
) -> list[dict]:
    """Rerank candidate documents using a provided reranker function.

    Workflow:
        1. Extract candidate['content'] texts
        2. Call reranker_fn(query, texts) -> list[float]
        3. Attach 'reranker_score' to each candidate dict (copy)
        4. Sort descending by reranker_score (stable sort preserves original order on ties)
        5. Filter by top_k and/or score_threshold
        6. Return reranked list

    Parameters
    ----------
    query : str
        Search query.
    candidates : list[dict]
        Candidate documents, each with a 'content' key.
    reranker_fn : callable
        (query, texts) -> list[float] scoring function.
    top_k : int or None
        Return at most top_k results.
    score_threshold : float or None
        Exclude results with reranker_score below this threshold.
    preserve_original_order_on_ties : bool
        If True, use a stable sort to preserve original order among tied scores.

    Returns
    -------
    list of candidate dicts with 'reranker_score' field added, sorted by score.

    Raises
    ------
    ValueError
        If len(reranker_fn output) != len(candidates).
    """
    if not candidates:
        return []

    texts = [c.get("content", "") for c in candidates]
    scores = reranker_fn(query, texts)

    if len(scores) != len(candidates):
        raise ValueError(
            f"reranker_fn returned {len(scores)} scores but there are {len(candidates)} candidates"
        )

    # Attach scores (copy dicts to avoid mutation of originals)
    scored = [
        {**candidate, "reranker_score": score} for candidate, score in zip(candidates, scores)
    ]

    # Sort descending (stable sort preserves original order on ties when flag is set)
    if preserve_original_order_on_ties:
        # Python's sort is stable, so equal elements keep their original order
        scored.sort(key=lambda x: x["reranker_score"], reverse=True)
    else:
        # Non-stable: use negative index as secondary key to break ties arbitrarily
        indexed = list(enumerate(scored))
        indexed.sort(key=lambda x: (-x[1]["reranker_score"], x[0]))
        scored = [item for _, item in indexed]

    # Filter by score threshold
    if score_threshold is not None:
        scored = [c for c in scored if c["reranker_score"] >= score_threshold]

    # Filter by top_k
    if top_k is not None:
        scored = scored[:top_k]

    return scored
