from __future__ import annotations

from obase.workflow_engine import WorkflowEngine
from oprim._hevi_types import CanvasEdge, CanvasNode
from oprim.canvas_edge_validate import canvas_edge_validate


class GraphValidationError(Exception):
    """Raised when canvas graph fails validation."""


def validate_edges(nodes: list[CanvasNode], edges: list[CanvasEdge]) -> list[str]:
    """Return list of incompatible edge descriptions (empty = all valid)."""
    node_types: dict[str, str] = {n.node_id: n.node_type for n in nodes}
    errors: list[str] = []
    for edge in edges:
        from_type = edge.from_type or node_types.get(edge.from_node_id, "")
        to_type = edge.to_type or node_types.get(edge.to_node_id, "")
        if from_type and to_type and not canvas_edge_validate(from_type=from_type, to_type=to_type):
            errors.append(f"Incompatible edge {edge.edge_id!r}: {from_type!r} → {to_type!r}")
    return errors


def detect_cycle(nodes: list[CanvasNode], edges: list[CanvasEdge]) -> None:
    """Raise CycleError if the graph contains a directed cycle."""
    node_ids = [n.node_id for n in nodes]
    edge_pairs = [(e.from_node_id, e.to_node_id) for e in edges]
    WorkflowEngine.detect_cycle(node_ids, edge_pairs)


def check_orphans(nodes: list[CanvasNode], edges: list[CanvasEdge]) -> list[str]:
    """Return node_ids with no connections in a multi-node graph."""
    if len(nodes) <= 1:
        return []
    connected: set[str] = set()
    for edge in edges:
        connected.add(edge.from_node_id)
        connected.add(edge.to_node_id)
    return [n.node_id for n in nodes if n.node_id not in connected]


def validate_graph(nodes: list[CanvasNode], edges: list[CanvasEdge]) -> None:
    """Full graph validation: edges compatible + acyclic.

    Raises:
        GraphValidationError: on incompatible edges.
        CycleError: if the graph contains a cycle.
    """
    if not nodes:
        raise GraphValidationError("Graph must contain at least one node")

    edge_errors = validate_edges(nodes, edges)
    if edge_errors:
        raise GraphValidationError("Invalid edges: " + "; ".join(edge_errors))

    detect_cycle(nodes, edges)
