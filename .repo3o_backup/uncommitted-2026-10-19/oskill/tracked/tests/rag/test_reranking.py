"""Tests for reranker_score."""

from __future__ import annotations

import pytest

from oskill.rag.reranking import reranker_score

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_candidates(n: int) -> list[dict]:
    return [
        {"content": f"Document {i} about topic.", "doc_id": i, "original_score": 0.5}
        for i in range(n)
    ]


def simple_reranker(query: str, texts: list[str]) -> list[float]:
    """Score based on text length (longer = more relevant, as mock)."""
    return [float(len(t)) for t in texts]


def fixed_reranker(scores: list[float]):
    """Return a reranker that always gives the provided scores."""

    def _fn(query: str, texts: list[str]) -> list[float]:
        return list(scores)

    return _fn


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_reranker_score_basic_reordering():
    """Candidates should be sorted by descending reranker_score."""
    candidates = [
        {"content": "short"},
        {"content": "much longer document text here"},
        {"content": "medium length content"},
    ]
    result = reranker_score("query", candidates, simple_reranker)
    scores = [r["reranker_score"] for r in result]
    assert scores == sorted(scores, reverse=True)


def test_reranker_score_top_k_filter():
    candidates = make_candidates(10)
    result = reranker_score("query", candidates, simple_reranker, top_k=3)
    assert len(result) == 3


def test_reranker_score_threshold_filter():
    candidates = [
        {"content": "Document A"},
        {"content": "Doc B"},
        {"content": "This is a longer document C"},
    ]
    scores = [0.9, 0.3, 0.8]
    result = reranker_score("query", candidates, fixed_reranker(scores), score_threshold=0.5)
    assert all(r["reranker_score"] >= 0.5 for r in result)
    assert len(result) == 2


def test_reranker_score_preserves_original_fields():
    candidates = [
        {"content": "Doc A", "custom_field": "value1"},
        {"content": "Doc B", "custom_field": "value2"},
    ]
    result = reranker_score("query", candidates, fixed_reranker([0.8, 0.3]))
    for r in result:
        assert "custom_field" in r
        assert "content" in r


def test_reranker_score_adds_reranker_score_field():
    candidates = make_candidates(3)
    result = reranker_score("query", candidates, simple_reranker)
    for r in result:
        assert "reranker_score" in r
        assert isinstance(r["reranker_score"], float)


def test_reranker_score_handles_ties():
    """Preserve original order on tied scores when preserve_original_order_on_ties=True."""
    candidates = [
        {"content": "Doc A", "order": 0},
        {"content": "Doc B", "order": 1},
        {"content": "Doc C", "order": 2},
    ]
    tied_reranker = fixed_reranker([0.5, 0.5, 0.5])
    result = reranker_score(
        "query", candidates, tied_reranker, preserve_original_order_on_ties=True
    )
    # All same score, order should be preserved
    assert [r["order"] for r in result] == [0, 1, 2]


def test_reranker_score_empty_candidates_returns_empty():
    result = reranker_score("query", [], simple_reranker)
    assert result == []


def test_reranker_score_mismatched_scores_length_raises():
    candidates = make_candidates(3)

    def bad_reranker(query: str, texts: list[str]) -> list[float]:
        return [0.5, 0.3]  # Only 2 scores for 3 candidates

    with pytest.raises(ValueError, match="3 candidates"):
        reranker_score("query", candidates, bad_reranker)


# ---------------------------------------------------------------------------
# Academic reference test
# ---------------------------------------------------------------------------


@pytest.mark.academic_reference
def test_reranker_score_nogueira_cho_pattern():
    """Test reranking pattern from Nogueira & Cho (2019) MonoBERT reranking.

    Reference: Nogueira, R. & Cho, K. (2019). "Passage Re-ranking with BERT."
    arXiv:1901.04085. The key pattern: a first-stage retriever returns candidates
    in BM25 order; a reranker re-scores and re-sorts for higher precision@k.

    This test verifies that reranker_score correctly implements the pattern of
    applying a cross-encoder score and returning top-k results.
    """
    # Simulate BM25 retrieval order
    bm25_candidates = [
        {"content": "The cat sat on the mat", "bm25_score": 0.9, "doc_id": 1},
        {"content": "Cats are mammals", "bm25_score": 0.7, "doc_id": 2},
        {"content": "The quick brown fox", "bm25_score": 0.6, "doc_id": 3},
        {"content": "Feline behavior patterns", "bm25_score": 0.5, "doc_id": 4},
        {"content": "Matrix multiplication in linear algebra", "bm25_score": 0.4, "doc_id": 5},
    ]

    query = "cat behavior"

    # Simulate cross-encoder re-scoring (higher relevance for doc_id 2, 4)
    cross_encoder_scores = [0.3, 0.95, 0.2, 0.85, 0.1]
    reranker = fixed_reranker(cross_encoder_scores)

    result = reranker_score(query, bm25_candidates, reranker, top_k=3)

    # Top-3 should contain doc_id 2 (score 0.95) and doc_id 4 (score 0.85)
    assert len(result) == 3
    result_ids = [r["doc_id"] for r in result]
    assert 2 in result_ids
    assert 4 in result_ids

    # Verify descending order
    scores = [r["reranker_score"] for r in result]
    assert scores == sorted(scores, reverse=True)

    # Verify BM25 fields are preserved
    for r in result:
        assert "bm25_score" in r
        assert "doc_id" in r
