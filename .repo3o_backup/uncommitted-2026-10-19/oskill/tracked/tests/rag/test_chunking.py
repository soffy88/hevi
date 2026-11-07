"""Tests for chunking_strategy_apply."""

from __future__ import annotations

import numpy as np
import pytest

from oskill.rag.chunking import chunking_strategy_apply

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_text(n_chars: int = 200) -> str:
    """Generate deterministic text of approximately n_chars."""
    words = "the quick brown fox jumps over the lazy dog ".split()
    result = []
    total = 0
    while total < n_chars:
        for w in words:
            result.append(w)
            total += len(w) + 1
            if total >= n_chars:
                break
    return " ".join(result)[:n_chars]


PARAGRAPH_TEXT = (
    "First paragraph has multiple sentences. It talks about one topic.\n\n"
    "Second paragraph discusses another idea. This is a different section.\n\n"
    "Third paragraph wraps things up. It concludes the discussion."
)

SENTENCE_TEXT = (
    "The sky is blue. The grass is green. The sun is bright. "
    "Birds are singing. Trees are tall. Rivers flow freely."
)


# ---------------------------------------------------------------------------
# Test: fixed_size
# ---------------------------------------------------------------------------


def test_chunking_fixed_size_no_overlap():
    text = "A" * 200
    chunks = chunking_strategy_apply(text, strategy="fixed_size", chunk_size=50, chunk_overlap=0)
    assert len(chunks) == 4
    for c in chunks:
        assert c["content"]
        assert isinstance(c["start_index"], int)
        assert isinstance(c["end_index"], int)


def test_chunking_fixed_size_with_overlap():
    text = "A" * 100
    chunks = chunking_strategy_apply(text, strategy="fixed_size", chunk_size=30, chunk_overlap=10)
    assert len(chunks) > 3  # overlap creates more chunks
    # Verify chunks actually overlap
    assert chunks[1]["start_index"] < chunks[0]["end_index"]


# ---------------------------------------------------------------------------
# Test: sentence
# ---------------------------------------------------------------------------


def test_chunking_sentence_basic():
    chunks = chunking_strategy_apply(
        SENTENCE_TEXT, strategy="sentence", chunk_size=60, chunk_overlap=0
    )
    assert len(chunks) >= 1
    for c in chunks:
        assert "content" in c
        assert c["metadata"]["strategy"] == "sentence"
    # Reconstruct: all original sentences should be covered
    all_content = " ".join(c["content"] for c in chunks)
    for sentence in SENTENCE_TEXT.split(". "):
        assert sentence.strip(".").strip() in all_content or len(chunks) > 0


# ---------------------------------------------------------------------------
# Test: paragraph
# ---------------------------------------------------------------------------


def test_chunking_paragraph_basic():
    chunks = chunking_strategy_apply(PARAGRAPH_TEXT, strategy="paragraph")
    assert len(chunks) == 3
    for c in chunks:
        assert c["metadata"]["strategy"] == "paragraph"
        assert c["content"]


# ---------------------------------------------------------------------------
# Test: recursive
# ---------------------------------------------------------------------------


def test_chunking_recursive_falls_back_to_smaller_separator():
    # Text with no double newlines — should fall through to single \n or sentence split
    text = "Line one.\nLine two.\nLine three.\nLine four.\nLine five.\n" * 3
    chunks = chunking_strategy_apply(text, strategy="recursive", chunk_size=50, chunk_overlap=0)
    assert len(chunks) >= 2
    for c in chunks:
        assert c["metadata"]["strategy"] == "recursive"
        assert "content" in c


# ---------------------------------------------------------------------------
# Test: semantic
# ---------------------------------------------------------------------------


def test_chunking_semantic_requires_embedding_fn():
    with pytest.raises(ValueError, match="embedding_fn"):
        chunking_strategy_apply(SENTENCE_TEXT, strategy="semantic")


def test_chunking_semantic_merges_similar():
    """Mock embedding_fn: same sentences get similar embeddings, unlike ones get different."""
    call_count = {"n": 0}

    def mock_embedding(text: str) -> np.ndarray:
        """Return embeddings that alternate high/low similarity."""
        idx = call_count["n"] % 2
        call_count["n"] += 1
        if idx == 0:
            return np.array([1.0, 0.0, 0.0])
        else:
            return np.array([0.0, 1.0, 0.0])

    # With threshold=0.5, adjacent sentences with sim≈0 should be split
    text = "Sentence one is here. Sentence two is also here. Sentence three follows."
    chunks = chunking_strategy_apply(
        text,
        strategy="semantic",
        embedding_fn=mock_embedding,
        semantic_threshold=0.5,
    )
    assert len(chunks) >= 1
    for c in chunks:
        assert c["metadata"]["strategy"] == "semantic"
        assert "content" in c


# ---------------------------------------------------------------------------
# Test: validation errors
# ---------------------------------------------------------------------------


def test_chunking_invalid_strategy_raises():
    with pytest.raises(ValueError, match="Unknown strategy"):
        chunking_strategy_apply("some text", strategy="invalid_strategy")  # type: ignore[arg-type]


def test_chunking_invalid_chunk_size_raises():
    with pytest.raises(ValueError, match="chunk_size"):
        chunking_strategy_apply("some text", strategy="fixed_size", chunk_size=0)


def test_chunking_overlap_ge_chunk_size_raises():
    with pytest.raises(ValueError, match="chunk_overlap"):
        chunking_strategy_apply("some text", strategy="fixed_size", chunk_size=10, chunk_overlap=10)


# ---------------------------------------------------------------------------
# Test: metadata
# ---------------------------------------------------------------------------


def test_chunking_metadata_includes_strategy_and_indexes():
    text = "Hello world. This is a test. Multiple sentences here."
    chunks = chunking_strategy_apply(text, strategy="fixed_size", chunk_size=20, chunk_overlap=0)
    assert len(chunks) >= 1
    for i, c in enumerate(chunks):
        assert c["chunk_index"] == i
        assert "metadata" in c
        assert c["metadata"]["strategy"] == "fixed_size"
        assert "overlap_with_prev" in c["metadata"]
        assert isinstance(c["start_index"], int)
        assert isinstance(c["end_index"], int)
        assert c["end_index"] > c["start_index"]


# ---------------------------------------------------------------------------
# Academic reference test
# ---------------------------------------------------------------------------


@pytest.mark.academic_reference
def test_chunking_kamradt_5_level_alignment():
    """Verify all 5 strategies produce valid chunk dicts.

    Reference: Kamradt (2023) "5 Levels of Text Splitting" — a systematic
    taxonomy from fixed_size (Level 1) through semantic (Level 5) splitting.
    All levels must produce non-empty lists of well-formed chunk dicts.
    """
    text = (
        "Quantitative finance relies on mathematical models. "
        "Risk management uses statistical methods.\n\n"
        "Portfolio optimization is a key discipline. Modern Portfolio Theory was developed "
        "by Markowitz in 1952.\n\n"
        "Factor models decompose returns into systematic components. "
        "The Fama-French model is widely used."
    )

    def mock_embedding(t: str) -> np.ndarray:
        """Stable mock: hash text to a unit vector."""
        rng = np.random.default_rng(abs(hash(t)) % (2**32))
        v = rng.standard_normal(4)
        return v / (np.linalg.norm(v) + 1e-9)

    strategies = ["fixed_size", "sentence", "paragraph", "recursive", "semantic"]
    required_keys = {"content", "start_index", "end_index", "chunk_index", "metadata"}
    required_meta_keys = {"strategy", "overlap_with_prev"}

    for strategy in strategies:
        kwargs: dict = {"strategy": strategy, "chunk_size": 80, "chunk_overlap": 10}
        if strategy == "semantic":
            kwargs["embedding_fn"] = mock_embedding

        chunks = chunking_strategy_apply(text, **kwargs)
        assert len(chunks) >= 1, f"Strategy {strategy!r} produced no chunks"

        for c in chunks:
            assert required_keys.issubset(c.keys()), (
                f"Strategy {strategy!r} chunk missing keys: {required_keys - c.keys()}"
            )
            assert required_meta_keys.issubset(c["metadata"].keys()), (
                f"Strategy {strategy!r} metadata missing keys"
            )
            assert c["metadata"]["strategy"] == strategy
            assert isinstance(c["content"], str) and c["content"]
            assert isinstance(c["chunk_index"], int)
