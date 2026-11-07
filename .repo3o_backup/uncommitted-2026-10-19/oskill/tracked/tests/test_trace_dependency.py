"""Tests for oskill.trace_dependency."""

from oskill.trace_dependency import trace_dependency


class _Edge:
    def __init__(self, dst_id, relation="depends_on"):
        self.dst_id = dst_id
        self.relation = relation


def _no_edges(nid):
    return []


def _no_node(nid):
    return None


def test_empty_graph_returns_empty_reached():
    result = trace_dependency(
        node_id="A",
        list_edges=_no_edges,
        get_node=_no_node,
        max_hops=3,
    )
    assert result["reached"] == []
    assert result["root"] == "A"


def test_direct_edge_traced():
    edge_map = {"A": [_Edge("B")]}

    def list_edges(nid):
        return edge_map.get(nid, [])

    result = trace_dependency(
        node_id="A",
        list_edges=list_edges,
        get_node=_no_node,
        max_hops=1,
    )
    assert "B" in result["reached"]
    assert any(e["dst"] == "B" for e in result["edges"])


def test_two_hop_chain_traced():
    edge_map = {"A": [_Edge("B")], "B": [_Edge("C")]}

    def list_edges(nid):
        return edge_map.get(nid, [])

    result = trace_dependency(
        node_id="A",
        list_edges=list_edges,
        get_node=_no_node,
        max_hops=2,
    )
    assert "B" in result["reached"]
    assert "C" in result["reached"]


def test_max_hops_limits_depth():
    # Chain A->B->C->D, but max_hops=1 should only reach B
    edge_map = {"A": [_Edge("B")], "B": [_Edge("C")], "C": [_Edge("D")]}

    def list_edges(nid):
        return edge_map.get(nid, [])

    result = trace_dependency(
        node_id="A",
        list_edges=list_edges,
        get_node=_no_node,
        max_hops=1,
    )
    assert "B" in result["reached"]
    assert "C" not in result["reached"]
    assert "D" not in result["reached"]


def test_circular_references_no_infinite_loop():
    # A->B->A cycle should not loop forever
    edge_map = {"A": [_Edge("B")], "B": [_Edge("A"), _Edge("C")]}

    def list_edges(nid):
        return edge_map.get(nid, [])

    result = trace_dependency(
        node_id="A",
        list_edges=list_edges,
        get_node=_no_node,
        max_hops=5,
    )
    # Should complete without hanging; C should be reachable
    assert "B" in result["reached"]
    assert "C" in result["reached"]


def test_returns_root_in_result():
    result = trace_dependency(
        node_id="root_node",
        list_edges=_no_edges,
        get_node=_no_node,
        max_hops=3,
    )
    assert result["root"] == "root_node"


def test_edges_list_contains_relation_info():
    edge_map = {"X": [_Edge("Y", relation="supersedes")]}

    def list_edges(nid):
        return edge_map.get(nid, [])

    result = trace_dependency(
        node_id="X",
        list_edges=list_edges,
        get_node=_no_node,
        max_hops=1,
    )
    assert len(result["edges"]) >= 1
    edge = result["edges"][0]
    assert "relation" in edge
    assert edge["relation"] == "supersedes"
    assert edge["src"] == "X"
    assert edge["dst"] == "Y"


def test_coherence_summary_key_present():
    result = trace_dependency(
        node_id="A",
        list_edges=_no_edges,
        get_node=_no_node,
        max_hops=3,
    )
    assert "coherence_summary" in result
    cs = result["coherence_summary"]
    assert "total_nodes" in cs
    assert "supported" in cs
    assert "contradicted" in cs


def test_coherence_summary_with_nodes():
    edge_map = {"A": [_Edge("B", "supports")]}
    nodes = {
        "A": {
            "epistemic_status": {
                "completeness": {"grade": "high", "source": "reproducible_empirical"}
            }
        },
        "B": {"epistemic_status": {"completeness": {"grade": "unverified"}}},
    }

    def list_edges(nid):
        return edge_map.get(nid, [])

    def get_node(nid):
        return nodes.get(nid)

    result = trace_dependency(
        node_id="A",
        list_edges=list_edges,
        get_node=get_node,
        max_hops=1,
    )
    assert result["coherence_summary"]["total_nodes"] >= 1
