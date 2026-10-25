from __future__ import annotations

from obase.workflow_engine import WorkflowEngine
from oprim.hevi_types import CanvasEdge, CanvasNode


class GraphValidationError(Exception):
    """Raised when canvas graph fails validation."""


# ── Edge compatibility: the single source of truth (hevi-owned) ─────────────
#
# This module -- NOT oprim.canvas_edge_validate, NOT the frontend
# canvas-rules.ts -- is authoritative for which canvas edges are legal.
# Rationale: hevi is the product being shipped; its workflow shapes
# (notably the 7-type workflow chain via workflow_adapter) define the
# edges that must be legal, and a dependency matrix that a reinstall
# can silently change must never be able to veto a hevi workflow.
#
# Boundary with oprim (deliberate, do not "fix" by re-importing it):
# oprim.canvas_edge_validate.COMPATIBLE is reference-only. It is NOT
# consulted anywhere in this decision path, so a reinstall/upgrade of
# oprim cannot reintroduce a rejection hevi has cured, and a future
# oprim change cannot silently legalise an edge hevi has not approved.
# If oprim ever needs to change, the change is made HERE first and the
# frontend matrix is mirrored from here (see tests/test_canvas_edge_matrix.py,
# which fails loudly on any front/back divergence).
#
# The 14 edges, with the two cured additions marked:
# - script -> audio: a script drives narration / TTS audio. The frontend
#   already allowed this; the old oprim matrix did not, so a script ->
#   audio workflow graph was drawable but unexecutable. Now legal.
# - video -> text: a video drives its subtitle (text) node. Neither
#   matrix allowed this, so the canonical 7-type chain
#   (video -> subtitle -> assemble) could never execute. Now legal.
# - video -> audio and image -> script: retained, not newly invented.
#   video -> audio was frontend-legal (extract / dub audio from video)
#   and image -> script was backend-legal under oprim; dropping either
#   would have made a previously legal graph illegal, so the cured
#   matrix is the union of both prior matrices plus video -> text.
# Every other pair stays illegal (in particular audio -> text and all
# same-type pairs except image -> image and video -> video).
EDGE_MATRIX: dict[str, frozenset[str]] = {
    # text drives image / video / audio / script
    "text": frozenset({"image", "video", "audio", "script"}),
    # image feeds video, chains to image, inspires script
    "image": frozenset({"video", "image", "script"}),
    # video chains to video, yields audio, drives subtitles (text)
    "video": frozenset({"video", "audio", "text"}),
    # audio merges into video
    "audio": frozenset({"video"}),
    # script drives image / video / audio
    "script": frozenset({"image", "video", "audio"}),
}

EDGE_COMPATIBLE: frozenset[tuple[str, str]] = frozenset(
    (from_type, to_type)
    for from_type, targets in EDGE_MATRIX.items()
    for to_type in targets
)


def edge_compatible(*, from_type: str, to_type: str) -> bool:
    """Return True iff the hevi matrix allows ``from_type -> to_type``.

    This is the only edge-compatibility decision in hevi. Callers that
    used to call ``oprim.canvas_edge_validate`` must call this instead.
    """
    return (from_type, to_type) in EDGE_COMPATIBLE


def validate_edges(nodes: list[CanvasNode], edges: list[CanvasEdge]) -> list[str]:
    """Return list of incompatible edge descriptions (empty = all valid)."""
    node_types: dict[str, str] = {n.node_id: n.node_type for n in nodes}
    errors: list[str] = []
    for edge in edges:
        from_type = edge.from_type or node_types.get(edge.from_node_id, "")
        to_type = edge.to_type or node_types.get(edge.to_node_id, "")
        if from_type and to_type and not edge_compatible(from_type=from_type, to_type=to_type):
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
