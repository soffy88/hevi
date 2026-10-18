"""Tests for oskill.hybrid_retrieve."""

from oskill.hybrid_retrieve import hybrid_retrieve


class _Edge:
    def __init__(self, dst_id):
        self.dst_id = dst_id


def _no_edges(nid):
    return []


def test_empty_docs_and_empty_seeds_returns_empty():
    result = hybrid_retrieve(
        query="hello",
        docs={},
        seed_ids=[],
        list_edges=_no_edges,
        top_k=5,
    )
    assert result == []


def test_bm25_hit_surfaces_result():
    docs = {"adr1": "ADR-001 architecture decision record", "other": "unrelated"}
    result = hybrid_retrieve(
        query="ADR-001",
        docs=docs,
        seed_ids=[],
        list_edges=_no_edges,
        top_k=5,
    )
    ids = [r[0] for r in result]
    assert "adr1" in ids


def test_graph_hit_surfaces_result():
    # seed "A" has edge to "B"; query matches nothing in docs
    docs = {}
    edge_map = {"A": [_Edge("B"), _Edge("C")]}

    def list_edges(nid):
        return edge_map.get(nid, [])

    result = hybrid_retrieve(
        query="zzz",
        docs=docs,
        seed_ids=["A"],
        list_edges=list_edges,
        top_k=5,
    )
    ids = [r[0] for r in result]
    assert "B" in ids


def test_both_signals_reinforce_same_doc():
    """Doc appearing in both BM25 and graph results should score higher than doc in only one."""
    docs = {"shared": "machine learning algorithm", "bm25only": "machine learning elsewhere"}
    edge_map = {"seed": [_Edge("shared"), _Edge("graphonly")]}

    def list_edges(nid):
        return edge_map.get(nid, [])

    result = hybrid_retrieve(
        query="machine learning",
        docs=docs,
        seed_ids=["seed"],
        list_edges=list_edges,
        top_k=10,
    )
    score_map = {r[0]: r[1] for r in result}
    # shared appears in both signals, graphonly only in graph, bm25only only in BM25
    assert "shared" in score_map
    # shared score should be >= graphonly and >= bm25only (could tie, but not lower)
    if "graphonly" in score_map:
        assert score_map["shared"] >= score_map["graphonly"]
    if "bm25only" in score_map:
        assert score_map["shared"] >= score_map["bm25only"]


def test_top_k_limits_output():
    docs = {f"doc{i}": f"common word doc{i}" for i in range(20)}
    result = hybrid_retrieve(
        query="common word",
        docs=docs,
        seed_ids=[],
        list_edges=_no_edges,
        top_k=3,
    )
    assert len(result) <= 3


def test_rrf_scores_are_floats():
    docs = {"a": "hello world"}
    result = hybrid_retrieve(
        query="hello",
        docs=docs,
        seed_ids=[],
        list_edges=_no_edges,
        top_k=5,
    )
    for doc_id, score in result:
        assert isinstance(score, float)


def test_results_sorted_descending():
    docs = {
        "d1": "python python python",
        "d2": "python once",
        "d3": "java coffee",
    }
    result = hybrid_retrieve(
        query="python",
        docs=docs,
        seed_ids=[],
        list_edges=_no_edges,
        top_k=10,
    )
    scores = [s for _, s in result]
    assert scores == sorted(scores, reverse=True)


def test_no_edge_graph_still_returns_bm25_results():
    docs = {"found": "special term identifier", "other": "unrelated noise"}
    result = hybrid_retrieve(
        query="special term",
        docs=docs,
        seed_ids=["nonexistent_node"],
        list_edges=_no_edges,
        top_k=5,
    )
    ids = [r[0] for r in result]
    assert "found" in ids


def test_result_is_list_of_str_float_tuples():
    docs = {"a": "hello world"}
    result = hybrid_retrieve(
        query="hello",
        docs=docs,
        seed_ids=[],
        list_edges=_no_edges,
        top_k=5,
    )
    assert isinstance(result, list)
    for item in result:
        assert isinstance(item, tuple)
        assert len(item) == 2
        assert isinstance(item[0], str)
        assert isinstance(item[1], float)
