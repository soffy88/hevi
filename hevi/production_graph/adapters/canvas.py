"""Canvas projection adapter.

Canvas layout may round-trip freely. A semantic edit must carry the canonical
production object ID and is converted to a RevisionPatch; a node label or
node ID is never treated as a production identity.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from hevi.production_graph.domain import RevisionPatch, RevisionPatchOperation


class CanvasProjectionNode(BaseModel):
    node_id: str
    node_type: str
    label: str = ""
    production_object_id: str | None = None
    production_type: str | None = None
    position: dict[str, float] = Field(default_factory=dict)
    config: dict[str, Any] = Field(default_factory=dict)


class CanvasProjection(BaseModel):
    graph_id: str
    project_id: str
    revision_id: str
    nodes: list[CanvasProjectionNode] = Field(default_factory=list)
    edges: list[dict[str, Any]] = Field(default_factory=list)
    viewport: dict[str, Any] = Field(default_factory=dict)
    grouping: dict[str, Any] = Field(default_factory=dict)


class CanvasProjectionError(ValueError):
    """Canvas data cannot be safely mapped to canonical semantics."""


def canvas_graph_to_projection(
    graph: dict[str, Any], *, project_id: str, revision_id: str
) -> CanvasProjection:
    nodes: list[CanvasProjectionNode] = []
    for raw in graph.get("nodes_json") or graph.get("nodes") or []:
        config = dict(raw.get("config") or {})
        nodes.append(
            CanvasProjectionNode(
                node_id=str(raw.get("node_id") or ""),
                node_type=str(raw.get("node_type") or ""),
                label=str(raw.get("label") or ""),
                production_object_id=(
                    str(raw["production_object_id"])
                    if raw.get("production_object_id")
                    else str(config["production_object_id"])
                    if config.get("production_object_id")
                    else None
                ),
                production_type=(
                    str(raw["production_type"])
                    if raw.get("production_type")
                    else str(config["production_type"])
                    if config.get("production_type")
                    else None
                ),
                position=dict(raw.get("position") or {}),
                config=config,
            )
        )
    return CanvasProjection(
        graph_id=str(graph.get("id") or ""),
        project_id=project_id,
        revision_id=revision_id,
        nodes=nodes,
        edges=list(graph.get("edges_json") or graph.get("edges") or []),
        viewport=dict(graph.get("viewport") or {}),
        grouping=dict(graph.get("grouping") or {}),
    )


def canvas_semantic_patch(
    *,
    project_id: str,
    revision_id: str,
    actor: str,
    reason: str,
    node: dict[str, Any],
    field: str,
    value: Any,
) -> RevisionPatch | None:
    """Convert one Canvas edit; layout-only edits return no production patch."""

    if field in {"position", "viewport", "group", "grouping", "ui_edge", "edge_metadata"}:
        return None
    config = node.get("config") or {}
    object_id = node.get("production_object_id") or config.get("production_object_id")
    production_type = node.get("production_type") or config.get("production_type")
    if not object_id or not production_type:
        raise CanvasProjectionError(
            "semantic Canvas edit requires production_object_id and production_type"
        )
    collection = str(production_type).strip()
    if collection not in {
        "characters",
        "character_states",
        "look_variants",
        "locations",
        "location_states",
        "props",
        "prop_states",
        "scenes",
        "beats",
        "shots",
        "keyframes",
    }:
        raise CanvasProjectionError(f"unsupported canonical Canvas production type: {collection}")
    return RevisionPatch(
        project_id=project_id,
        base_revision_id=revision_id,
        actor=actor,
        reason=reason,
        operations=[
            RevisionPatchOperation(
                op="replace", path=f"/{collection}/{object_id}/{field}", value=value
            )
        ],
    )


__all__ = [
    "CanvasProjection",
    "CanvasProjectionError",
    "CanvasProjectionNode",
    "canvas_graph_to_projection",
    "canvas_semantic_patch",
]
