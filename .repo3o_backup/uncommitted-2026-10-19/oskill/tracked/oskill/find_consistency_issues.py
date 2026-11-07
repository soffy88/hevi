"""oskill.find_consistency_issues — knowledge graph consistency validation.

3O layer: oskill (≥2 oprim composition, stateless, pure logic).

Internal oprim composition:
    - oprim.coherence_compute: coherence evidence for contradiction detection
    - oprim.entity_graph_search: graph structure for cycle detection
"""

from __future__ import annotations

import re
from collections import defaultdict

from oprim import coherence_compute, entity_graph_search


def find_consistency_issues(
    *,
    nodes: dict[str, dict],
    edges: list[tuple[str, str, str]],
    prefix_pattern: str = r"(ADR-\d+)",
) -> dict:
    """Find consistency issues in a knowledge graph.

    Args:
        nodes: {node_id: node_dict} — each node dict may contain a "title" field.
        edges: list of (src_id, relation, dst_id) triples.
        prefix_pattern: regex to detect label prefix conflicts (default ADR-xxx).

    Returns:
        {label_conflicts, coherence_contradictions, cycle_indicators, total_issues}

    Internal oprim composition:
        coherence_compute detects contradiction evidence from confirmed nodes.
        entity_graph_search finds supersede cycles via graph traversal.
    """
    # 1. Label conflicts via pattern matching (ported + enhanced from staging _cap_find_consistency_issues)
    buckets: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for nid, node in nodes.items():
        title = (node or {}).get("title", "")
        m = re.search(prefix_pattern, title)
        if m:
            buckets[m.group(1)].append((nid, title))
    label_conflicts = {k: v for k, v in buckets.items() if len(v) > 1}

    # 2. Coherence contradictions via oprim.coherence_compute
    coh = coherence_compute(nodes=nodes, edges=edges)
    coherence_contradictions = [
        {"node_id": nid, "contradictors": info["contradictors"]}
        for nid, info in coh.items()
        if info["contradicts_from_confirmed"] > 0
    ]

    # 3. Supersede cycles via oprim.entity_graph_search
    # Build a list_edges callable restricted to "supersedes" edges only
    supersede_map: dict[str, list] = defaultdict(list)

    class _Edge:
        __slots__ = ("dst_id",)

        def __init__(self, dst: str) -> None:
            self.dst_id = dst

    for src, relation, dst in edges:
        if relation == "supersedes":
            supersede_map[src].append(_Edge(dst))

    def _list_supersede_edges(nid: str) -> list:
        return supersede_map.get(nid, [])

    cycle_indicators: list[str] = []
    n_nodes = max(len(nodes), 1)
    for nid in nodes:
        neighbours = [e.dst_id for e in supersede_map.get(nid, [])]
        if not neighbours:
            continue
        # Seed from nid's direct neighbours; if nid appears in the reachable set,
        # there is a cycle. (entity_graph_search excludes seeds, not nid itself.)
        reached = entity_graph_search(
            seed_ids=neighbours,
            list_edges=_list_supersede_edges,
            hops=n_nodes,
            top_k=n_nodes + 1,
        )
        reached_ids = {r[0] for r in reached}
        # Also include the direct neighbours themselves in the reachable check
        # (entity_graph_search excludes seeds from results; cover 2-node cycles
        # where A->B->A: seed=[B], B's edge goes to A, so A appears in reached)
        if nid in reached_ids:
            cycle_indicators.append(nid)

    total_issues = len(label_conflicts) + len(coherence_contradictions) + len(cycle_indicators)

    return {
        "label_conflicts": label_conflicts,
        "coherence_contradictions": coherence_contradictions,
        "cycle_indicators": cycle_indicators,
        "total_issues": total_issues,
    }
