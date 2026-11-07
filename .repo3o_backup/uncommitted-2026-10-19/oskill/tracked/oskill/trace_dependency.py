"""oskill.trace_dependency — multi-hop dependency chain traversal.

3O layer: oskill (≥2 oprim composition, stateless).

Internal oprim composition:
    - oprim.entity_graph_search: N-hop traversal to find reachable nodes
    - oprim.coherence_compute: assess coherence of dependency chain nodes
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable

from oprim import coherence_compute, entity_graph_search


def trace_dependency(
    *,
    node_id: str,
    list_edges: Callable,
    get_node: Callable,
    max_hops: int = 3,
) -> dict:
    """Trace dependency chain from a node via relation edges.

    Args:
        node_id: Root node to trace from.
        list_edges: callable(node_id) -> list of edge objects with .dst_id and .relation.
        get_node: callable(node_id) -> dict | None
        max_hops: Maximum traversal depth (default 3).

    Returns:
        {root, edges, reached, coherence_summary}

    Internal oprim composition:
        entity_graph_search finds all reachable nodes up to max_hops.
        coherence_compute assesses knowledge coherence of chain nodes.
    """
    # 1. Use entity_graph_search to find reachable nodes
    reachable = entity_graph_search(
        seed_ids=[node_id], list_edges=list_edges, hops=max_hops, top_k=1000
    )
    reached_ids = [nid for nid, _ in reachable]

    # 2. Build edge chain via BFS with relation tracking (handles circular refs via seen set)
    chain_edges: list[dict] = []
    visited: set[str] = {node_id}
    queue: deque[tuple[str, int]] = deque([(node_id, 0)])
    while queue:
        current, depth = queue.popleft()
        if depth >= max_hops:
            continue
        for e in list_edges(current):
            dst = e.dst_id
            relation = getattr(e, "relation", "unknown")
            chain_edges.append({"src": current, "dst": dst, "relation": relation})
            if dst not in visited:
                visited.add(dst)
                queue.append((dst, depth + 1))

    # 3. Use coherence_compute to assess nodes in the chain
    chain_nodes = {nid: get_node(nid) for nid in reached_ids if get_node(nid) is not None}
    # Build edge tuples in (src, relation, dst) format for coherence_compute
    coh_edges = [(e["src"], e["relation"], e["dst"]) for e in chain_edges]
    # Include root in nodes map for coherence context
    root_node = get_node(node_id)
    if root_node is not None:
        chain_nodes[node_id] = root_node

    coh = coherence_compute(nodes=chain_nodes, edges=coh_edges) if chain_nodes else {}

    coherence_summary = {
        "total_nodes": len(chain_nodes),
        "supported": sum(1 for v in coh.values() if v["supports_from_confirmed"] > 0),
        "contradicted": sum(1 for v in coh.values() if v["contradicts_from_confirmed"] > 0),
        "details": coh,
    }

    return {
        "root": node_id,
        "edges": chain_edges,
        "reached": reached_ids,
        "coherence_summary": coherence_summary,
    }
