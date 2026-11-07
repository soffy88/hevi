from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from oskill._exceptions import OskillError
from oskill.hybrid_search import SearchResult, hybrid_search


@pytest.mark.asyncio
async def test_hybrid_search_empty_query():
    with pytest.raises(OskillError, match="Query cannot be empty"):
        await hybrid_search("", corpus_id="corpus1")


@pytest.mark.asyncio
async def test_hybrid_search_empty_corpus_id():
    with pytest.raises(OskillError, match="corpus_id cannot be empty"):
        await hybrid_search("test", corpus_id="")


@pytest.mark.asyncio
async def test_hybrid_search_basic():
    with (
        patch("oskill.hybrid_search._bm25_search", return_value=[("doc1", 1.0)]),
        patch("oskill.hybrid_search._dense_search", new_callable=AsyncMock) as mock_dense,
        patch(
            "oskill.hybrid_search._enrich",
            return_value=[
                SearchResult(type="sub", id="doc1", title="doc1", score=1.0, highlight="")
            ],
        ),
    ):
        mock_dense.return_value = [("doc1", 1.0)]
        res = await hybrid_search("test", corpus_id="c1", top_k=5)
        assert len(res) == 1
        assert res[0].id == "doc1"


@pytest.mark.asyncio
async def test_hybrid_search_expand():
    mock_expand = MagicMock(return_value=["test1", "test2"])

    with (
        patch("oskill.hybrid_search._bm25_search", return_value=[]) as mock_bm25,
        patch("oskill.hybrid_search._dense_search", new_callable=AsyncMock) as mock_dense,
    ):
        mock_dense.return_value = []
        await hybrid_search("test", corpus_id="c1", expand=mock_expand)

        mock_expand.assert_called_with(query="test", num_variants=3)
        assert mock_bm25.call_count == 2
        assert mock_dense.call_count == 2


@pytest.mark.asyncio
async def test_hybrid_search_rerank():
    mock_res = [
        SearchResult(type="sub", id="d1", title="T1", score=0.5, highlight="H1"),
        SearchResult(type="sub", id="d2", title="T2", score=0.8, highlight="H2"),
    ]

    mock_rerank_res = [
        MagicMock(original_index=1, score=0.9),
        MagicMock(original_index=0, score=0.1),
    ]
    mock_reranker = MagicMock(return_value=mock_rerank_res)

    with (
        patch("oskill.hybrid_search._bm25_search", return_value=[]),
        patch("oskill.hybrid_search._dense_search", new_callable=AsyncMock, return_value=[]),
        patch("oskill.hybrid_search._enrich", return_value=mock_res),
    ):
        res = await hybrid_search("test", corpus_id="c1", rerank=mock_reranker, rerank_top_k=2)
        assert len(res) == 2
        assert res[0].id == "d2"
        assert res[0].score == 0.9
        assert res[1].id == "d1"
        assert res[1].score == 0.1
        mock_reranker.assert_called_once()


@pytest.mark.asyncio
async def test_hybrid_search_mode_augmented_zero_hits():
    with (
        patch("oskill.hybrid_search._bm25_search", return_value=[]),
        patch("oskill.hybrid_search._dense_search", new_callable=AsyncMock, return_value=[]),
        patch("oskill.hybrid_search._enrich", return_value=[]),
        patch("oskill.hybrid_search._llm_augmented", new_callable=AsyncMock) as mock_llm,
    ):
        mock_llm.return_value = [
            SearchResult(type="llm", id="1", title="LLM", score=0.5, highlight="ans")
        ]

        res = await hybrid_search("test", corpus_id="c1", mode="augmented")
        assert len(res) == 1
        assert res[0].type == "llm"
