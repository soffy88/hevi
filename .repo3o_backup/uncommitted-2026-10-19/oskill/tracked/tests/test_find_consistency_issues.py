"""Tests for oskill.find_consistency_issues."""

from oskill.find_consistency_issues import find_consistency_issues


def test_empty_graph_all_zeros():
    result = find_consistency_issues(nodes={}, edges=[])
    assert result["label_conflicts"] == {}
    assert result["coherence_contradictions"] == []
    assert result["cycle_indicators"] == []
    assert result["total_issues"] == 0


def test_label_conflict_detected():
    nodes = {
        "n1": {"title": "ADR-001 first decision"},
        "n2": {"title": "ADR-001 duplicate decision"},
        "n3": {"title": "ADR-002 different"},
    }
    result = find_consistency_issues(nodes=nodes, edges=[])
    assert "ADR-001" in result["label_conflicts"]
    assert len(result["label_conflicts"]["ADR-001"]) == 2


def test_no_conflict_if_labels_differ():
    nodes = {
        "n1": {"title": "ADR-001 first"},
        "n2": {"title": "ADR-002 second"},
    }
    result = find_consistency_issues(nodes=nodes, edges=[])
    assert result["label_conflicts"] == {}
    assert result["total_issues"] == 0


def test_coherence_contradiction_detected():
    # n_confirmed is a confirmed node that contradicts n_target
    nodes = {
        "n_confirmed": {
            "title": "ADR-010 confirmed source",
            "epistemic_status": {
                "completeness": {"grade": "high", "source": "reproducible_empirical"}
            },
        },
        "n_target": {"title": "ADR-020 target node"},
    }
    edges = [("n_confirmed", "contradicts", "n_target")]
    result = find_consistency_issues(nodes=nodes, edges=edges)
    assert len(result["coherence_contradictions"]) == 1
    assert result["coherence_contradictions"][0]["node_id"] == "n_target"
    assert "n_confirmed" in result["coherence_contradictions"][0]["contradictors"]


def test_returns_total_issues_count():
    nodes = {
        "n1": {"title": "ADR-001 first"},
        "n2": {"title": "ADR-001 duplicate"},
    }
    result = find_consistency_issues(nodes=nodes, edges=[])
    assert result["total_issues"] == len(result["label_conflicts"]) + len(
        result["coherence_contradictions"]
    ) + len(result["cycle_indicators"])


def test_supersede_cycle_detected():
    # A supersedes B, B supersedes A — cycle
    nodes = {"A": {"title": "ADR-100 A"}, "B": {"title": "ADR-101 B"}}
    edges = [("A", "supersedes", "B"), ("B", "supersedes", "A")]
    result = find_consistency_issues(nodes=nodes, edges=edges)
    assert len(result["cycle_indicators"]) > 0
    # Both A and B should be flagged as part of the cycle
    assert "A" in result["cycle_indicators"] or "B" in result["cycle_indicators"]


def test_all_required_keys_present():
    result = find_consistency_issues(nodes={}, edges=[])
    assert "label_conflicts" in result
    assert "coherence_contradictions" in result
    assert "cycle_indicators" in result
    assert "total_issues" in result


def test_large_graph_with_mixed_issues():
    nodes = {}
    for i in range(10):
        nodes[f"n{i}"] = {"title": f"ADR-{i:03d} node {i}"}
    # Add a duplicate label conflict
    nodes["n_dup"] = {"title": "ADR-000 duplicate of n0"}
    # Add a confirmed contradicting node
    nodes["n_confirmed"] = {
        "title": "ADR-099 confirmed",
        "epistemic_status": {"completeness": {"grade": "moderate", "source": "formal_proof"}},
    }
    edges = [
        ("n_confirmed", "contradicts", "n1"),
        ("n2", "supersedes", "n3"),
        ("n3", "supersedes", "n2"),
    ]
    result = find_consistency_issues(nodes=nodes, edges=edges)
    assert result["total_issues"] > 0
    assert "ADR-000" in result["label_conflicts"]
    assert len(result["coherence_contradictions"]) >= 1
    assert len(result["cycle_indicators"]) >= 1


def test_no_supersede_cycle_when_chain_is_linear():
    nodes = {"A": {"title": "ADR-200 A"}, "B": {"title": "ADR-201 B"}, "C": {"title": "ADR-202 C"}}
    edges = [("A", "supersedes", "B"), ("B", "supersedes", "C")]
    result = find_consistency_issues(nodes=nodes, edges=edges)
    assert result["cycle_indicators"] == []
