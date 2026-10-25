"""Workflow <-> canvas graph adapter (``hevi.canvas.workflow_adapter``).

Wiring only: this module connects the grafted workflow model in
``hevi.capabilities.canvas_workflow`` to the existing infinite canvas
(``hevi.canvas`` + ``hevi-web`` React Flow UI). It creates no second
canvas system, adds no frontend, and does not touch
``hevi.canvas.node_mapper``: dispatch keeps working by canvas
``node_type``, and the workflow identity of a node rides inside its
``config`` under ``workflow_*`` keys (see below).

Mapping summary (full table in CANVAS_WIRING.md):

* script -> script (native, ``script_node_executor``)
* first_frame -> image (native, ``image_node_executor``)
* tail_frame -> image (native, ``image_node_executor``)
* video -> video (native, ``video_node_executor``)
* audio -> audio (native, ``audio_node_executor``)
* subtitle -> text (native, ``text_node_executor``)
* assemble -> video (native, ``video_node_executor``)

The four workflow types without an exact canvas counterpart
(first_frame, tail_frame, subtitle, assemble) have no dedicated
canvas type, so they reuse
the closest native canvas type and are distinguished only by
``config["workflow_type"]``. A future dedicated executor can be
attached without changing this mapping through the extension point
that already exists in ``create_node_executor``: a ``tool_id`` in the
node config is dispatched before the type map, so setting
``config["tool_id"]`` on a workflow node overrides execution while
the mapping here stays unchanged.

Graph shape produced/consumed here is the shape ``GraphService``
stores: ``{"nodes": [...], "edges": [...]}``, where a node is a
``CanvasNode``-shaped dict (``node_id``, ``node_type``, ``label``,
``config``, ``position``) plus a frontend ``status`` field, and an
edge is ``{"edge_id", "from_node_id", "to_node_id",
"from_type", "to_type"}``. ``graph_to_workflow`` also accepts the
storage shape ``{"nodes_json": [...], "edges_json": [...]}``.

Position: a workflow has no position, so ``workflow_to_graph``
auto-lays-out (column = longest-path depth, row = order inside the
column) unless a position is supplied, either through the
``positions`` argument or through a ``position`` extra key on the
workflow node (which ``graph_to_workflow(..., include_position=True)``
preserves). Position never leaks into workflow ``params``.

Status: workflow ``pending/done/failed/blocked`` maps to the
frontend ``TaskStatus`` subset ``pending/completed/failed/blocked``
on the graph node, and the exact workflow status is also kept in
``config["workflow_status"]``, which wins on the way back. A graph
status outside that subset (e.g. ``running``) with no workflow meta
is rejected rather than silently collapsed.

Edge legality: the adapter rejects edges the workflow model itself
rejects (unknown endpoint, duplicate edge, self-edge, cycle) and
rejects any node whose type cannot be mapped (no silent drops).
It does NOT reject edges that the legacy canvas compatibility
matrix would reject (e.g. script -> audio, video -> subtitle):
a valid workflow chain may use them, and dropping them would
corrupt the DAG. Those edges are reported by
``canvas_edge_warnings`` instead, because the existing
``ExecutorService``/``validate_graph`` path still enforces the old
matrix and will refuse such a graph at execution time. That gap is
a documented residual, not something the adapter papers over.

Rerun semantics: topological order, idempotent skip and the
3-failure blocked cap are delegated to
``hevi.capabilities.canvas_workflow`` (``plan_rerun`` /
``rerun_selection`` / ``apply_run_result``) and live in this
adapter layer, not in the existing executor: ``ExecutorService``
always runs a whole graph and has no skip concept, so a caller
that wants a selective rerun must honour the plan actions
(run vs skip) itself. Preflight, by contrast, is reused directly
(see ``run_preflight_for_workflow``).

All functions here are pure except ``run_preflight_for_workflow``
(which only reads node configs through the existing preflight
path) and make no network or generation calls.
"""

from __future__ import annotations

import copy
from typing import Any

from hevi.capabilities.canvas_workflow import (
    NODE_STATUSES,
    NODE_TYPES,
    apply_run_result,
    create_workflow,
    plan_rerun as _wf_plan_rerun,
    rerun_selection as _wf_rerun_selection,
)
from hevi.capabilities.errors import CapabilityError

__all__ = [
    "CANVAS_NATIVE_WORKFLOW",
    "GRAPH_STATUS_TO_WORKFLOW",
    "WORKFLOW_STATUS_TO_GRAPH",
    "WORKFLOW_TO_CANVAS",
    "WorkflowAdapterError",
    "as_graph_service_payload",
    "canvas_edge_warnings",
    "graph_to_workflow",
    "planned_graph",
    "plan_rerun",
    "rerun_order",
    "run_preflight_for_workflow",
    "apply_run_result_to_graph",
    "workflow_to_graph",
]


class WorkflowAdapterError(ValueError):
    """Raised when a workflow/graph conversion or rerun cannot be done.

    Subclasses ValueError so callers that already handle the canvas
    ``GraphValidationError`` family (also ValueError-adjacent in
    practice) can treat a mapping failure as a validation failure,
    while still being catchable specifically. A mapping failure is
    never a silent drop: unknown types, unmapped canvas types,
    unknown edge endpoints, duplicate edges and cycles all raise.
    """


# ── type / status maps ─────────────────────────────────────────────────────

WORKFLOW_TO_CANVAS: dict[str, str] = {
    "script": "script",
    "first_frame": "image",
    "tail_frame": "image",
    "video": "video",
    "audio": "audio",
    "subtitle": "text",
    "assemble": "video",
}

# Canvas types that map back to a workflow type without any meta:
# only the unambiguous ones. "image" is ambiguous (first_frame vs
# tail_frame) and "text" has no workflow counterpart, so a graph node
# of those types without workflow meta is an error, not a guess.
CANVAS_NATIVE_WORKFLOW: dict[str, str] = {
    "script": "script",
    "video": "video",
    "audio": "audio",
}

WORKFLOW_STATUS_TO_GRAPH: dict[str, str] = {
    "pending": "pending",
    "done": "completed",
    "failed": "failed",
    "blocked": "blocked",
}

GRAPH_STATUS_TO_WORKFLOW: dict[str, str] = {
    "pending": "pending",
    "completed": "done",
    "failed": "failed",
    "blocked": "blocked",
}

# Config keys the adapter owns. Params are flattened into config, so
# a param that happens to use one of these names is stashed under
# "workflow_params_collisions" and restored on the way back, keeping
# the round-trip exact for arbitrary params.
_META_KEYS: tuple[str, ...] = (
    "workflow_type",
    "workflow_status",
    "workflow_artifact",
    "workflow_attempts",
    "workflow_reason",
    "workflow_params_collisions",
)

_X_STEP = 240
_Y_STEP = 140


def _fail(message: str) -> None:
    raise WorkflowAdapterError(message)


def _normalize_workflow(workflow: Any) -> dict[str, Any]:
    if not isinstance(workflow, dict) or not isinstance(
        workflow.get("nodes"), list
    ):
        _fail("workflow must be a dict with a nodes list")
    try:
        return create_workflow(workflow["nodes"])
    except CapabilityError as exc:
        raise WorkflowAdapterError(str(exc)) from exc


def _depths(nodes: list[dict[str, Any]]) -> dict[str, int]:
    by_id = {n["node_id"]: n for n in nodes}
    memo: dict[str, int] = {}

    def depth(node_id: str) -> int:
        if node_id in memo:
            return memo[node_id]
        inputs = by_id[node_id].get("inputs", [])
        value = 0 if not inputs else 1 + max(depth(i) for i in inputs)
        memo[node_id] = value
        return value

    return {n["node_id"]: depth(n["node_id"]) for n in nodes}


def _validate_position(node_id: str, position: Any) -> dict[str, Any]:
    if not isinstance(position, dict):
        _fail(f"position for node {node_id!r} must be a dict with x/y")
    x = position.get("x")
    y = position.get("y")
    if (
        isinstance(x, bool)
        or isinstance(y, bool)
        or not isinstance(x, (int, float))
        or not isinstance(y, (int, float))
    ):
        _fail(f"position for node {node_id!r} must have numeric x and y")
    return {"x": x, "y": y}


def _node_config_for_workflow_node(node: dict[str, Any]) -> dict[str, Any]:
    params = copy.deepcopy(node.get("params", {}))
    collisions = {k: params[k] for k in _META_KEYS if k in params}
    config: dict[str, Any] = dict(params)
    config["workflow_type"] = node["type"]
    config["workflow_status"] = node.get("status", "pending")
    config["workflow_artifact"] = node.get("artifact")
    config["workflow_attempts"] = node.get("attempts", 0)
    if "reason" in node:
        config["workflow_reason"] = node["reason"]
    if collisions:
        config["workflow_params_collisions"] = collisions
    return config


def workflow_to_graph(
    workflow: Any,
    positions: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Convert a workflow dict to a canvas graph dict.

    ``positions`` (optional) maps node_id to ``{"x", "y"}`` and wins
    over a ``position`` extra key on a workflow node, which in turn
    wins over auto-layout. An unknown node_id in ``positions`` is an
    error, not ignored. Duplicate inputs on one node are an error:
    they would produce duplicate edges.
    """
    wf = _normalize_workflow(workflow)
    nodes = wf["nodes"]
    if positions is not None:
        if not isinstance(positions, dict):
            _fail("positions must be a dict of node_id to {x, y}")
        known = {n["node_id"] for n in nodes}
        for node_id in positions:
            if node_id not in known:
                _fail(f"positions names unknown node {node_id!r}")
    depths = _depths(nodes)
    column_rows: dict[int, int] = {}
    graph_nodes: list[dict[str, Any]] = []
    for node in nodes:
        node_id = node["node_id"]
        workflow_type = node["type"]
        canvas_type = WORKFLOW_TO_CANVAS.get(workflow_type)
        if canvas_type is None:
            _fail(f"no canvas mapping for workflow type {workflow_type!r}")
        if positions is not None and node_id in positions:
            position = _validate_position(node_id, positions[node_id])
        elif isinstance(node.get("position"), dict):
            position = _validate_position(node_id, node["position"])
        else:
            column = depths[node_id]
            row = column_rows.get(column, 0)
            column_rows[column] = row + 1
            position = {"x": column * _X_STEP, "y": row * _Y_STEP}
        label = node.get("label") if isinstance(node.get("label"), str) else node_id
        graph_nodes.append(
            {
                "node_id": node_id,
                "node_type": canvas_type,
                "label": label,
                "config": _node_config_for_workflow_node(node),
                "position": position,
                "status": WORKFLOW_STATUS_TO_GRAPH[node.get("status", "pending")],
            }
        )
    graph_edges: list[dict[str, Any]] = []
    seen_pairs: set[tuple[str, str]] = set()
    by_id = {n["node_id"]: n for n in nodes}
    for node in nodes:
        for upstream in node.get("inputs", []):
            pair = (upstream, node["node_id"])
            if pair in seen_pairs:
                _fail(
                    f"duplicate input {upstream!r} on node {node['node_id']!r}"
                )
            seen_pairs.add(pair)
            graph_edges.append(
                {
                    "edge_id": f"{upstream}__{node['node_id']}",
                    "from_node_id": upstream,
                    "to_node_id": node["node_id"],
                    "from_type": WORKFLOW_TO_CANVAS[by_id[upstream]["type"]],
                    "to_type": WORKFLOW_TO_CANVAS[node["type"]],
                }
            )
    return {"nodes": graph_nodes, "edges": graph_edges}


def _graph_nodes_edges(graph: Any) -> tuple[list[Any], list[Any]]:
    if not isinstance(graph, dict):
        _fail("graph must be a dict with nodes and edges lists")
    nodes = graph.get("nodes", graph.get("nodes_json"))
    edges = graph.get("edges", graph.get("edges_json"))
    if not isinstance(nodes, list):
        _fail("graph nodes must be a list")
    if edges is None:
        edges = []
    if not isinstance(edges, list):
        _fail("graph edges must be a list")
    return nodes, edges


def graph_to_workflow(
    graph: Any, *, include_position: bool = False
) -> dict[str, Any]:
    """Convert a canvas graph dict back to a workflow dict.

    A node is mapped by ``config["workflow_type"]`` when present
    (checked for consistency with its canvas type); otherwise only
    the unambiguous native canvas types (script/video/audio) map
    back. An ``image`` node without meta is ambiguous
    (first_frame vs tail_frame), a ``text`` node without meta has
    no workflow counterpart, and any other unknown canvas type is
    an error. Nothing is silently dropped: every graph node becomes
    exactly one workflow node, and every edge becomes an input.
    """
    raw_nodes, raw_edges = _graph_nodes_edges(graph)
    if not raw_nodes:
        _fail("graph must contain at least one node")
    graph_nodes: list[dict[str, Any]] = []
    by_id: dict[str, dict[str, Any]] = {}
    for raw in raw_nodes:
        if not isinstance(raw, dict):
            _fail("graph node must be a dict")
        node_id = raw.get("node_id")
        if not isinstance(node_id, str) or not node_id:
            _fail("graph node requires a non-empty string node_id")
        if node_id in by_id:
            _fail(f"duplicate graph node_id: {node_id!r}")
        node_type = raw.get("node_type")
        if not isinstance(node_type, str) or not node_type:
            _fail(f"graph node {node_id!r} requires a node_type")
        config = raw.get("config", {})
        if not isinstance(config, dict):
            _fail(f"graph node {node_id!r} config must be a dict")
        by_id[node_id] = raw
        graph_nodes.append(raw)
    inputs_of: dict[str, list[str]] = {n["node_id"]: [] for n in graph_nodes}
    seen_pairs: set[tuple[str, str]] = set()
    for raw_edge in raw_edges:
        if not isinstance(raw_edge, dict):
            _fail("graph edge must be a dict")
        src = raw_edge.get("from_node_id")
        dst = raw_edge.get("to_node_id")
        if src not in by_id:
            _fail(f"graph edge names unknown source node {src!r}")
        if dst not in by_id:
            _fail(f"graph edge names unknown target node {dst!r}")
        if (src, dst) in seen_pairs:
            _fail(f"duplicate graph edge {src!r} -> {dst!r}")
        seen_pairs.add((src, dst))
        inputs_of[dst].append(src)
    workflow_nodes: list[dict[str, Any]] = []
    for raw in graph_nodes:
        node_id = raw["node_id"]
        node_type = raw["node_type"]
        config = dict(raw.get("config", {}) or {})
        workflow_type = config.get("workflow_type")
        if workflow_type is not None:
            if workflow_type not in NODE_TYPES:
                _fail(
                    f"graph node {node_id!r} has unknown workflow_type "
                    f"{workflow_type!r}"
                )
            if WORKFLOW_TO_CANVAS[workflow_type] != node_type:
                _fail(
                    f"graph node {node_id!r} workflow_type "
                    f"{workflow_type!r} does not match canvas type "
                    f"{node_type!r}"
                )
        elif node_type in CANVAS_NATIVE_WORKFLOW:
            workflow_type = CANVAS_NATIVE_WORKFLOW[node_type]
        elif node_type == "image":
            _fail(
                f"graph node {node_id!r} is an image node without "
                "workflow_type: cannot tell first_frame from tail_frame"
            )
        elif node_type == "text":
            _fail(
                f"graph node {node_id!r} is a text node without "
                "workflow_type: no workflow counterpart for text"
            )
        else:
            _fail(
                f"graph node {node_id!r} has unmapped canvas type "
                f"{node_type!r}"
            )
        params = {k: v for k, v in config.items() if k not in _META_KEYS}
        collisions = config.get("workflow_params_collisions")
        if collisions is not None:
            if not isinstance(collisions, dict):
                _fail(
                    f"graph node {node_id!r} workflow_params_collisions "
                    "must be a dict"
                )
            params.update(copy.deepcopy(collisions))
        if "workflow_status" in config:
            status = config["workflow_status"]
            if status not in NODE_STATUSES:
                _fail(
                    f"graph node {node_id!r} has unknown workflow_status "
                    f"{status!r}"
                )
        elif "status" in raw and raw["status"] is not None:
            if raw["status"] not in GRAPH_STATUS_TO_WORKFLOW:
                _fail(
                    f"graph node {node_id!r} has unmapped graph status "
                    f"{raw['status']!r} and no workflow_status"
                )
            status = GRAPH_STATUS_TO_WORKFLOW[raw["status"]]
        else:
            status = "pending"
        artifact = config.get("workflow_artifact")
        if artifact is not None and not isinstance(artifact, str):
            _fail(f"graph node {node_id!r} workflow_artifact must be a string")
        attempts = config.get("workflow_attempts", 0)
        if (
            isinstance(attempts, bool)
            or not isinstance(attempts, int)
            or attempts < 0
        ):
            _fail(
                f"graph node {node_id!r} workflow_attempts must be a "
                "non-negative int"
            )
        node: dict[str, Any] = {
            "node_id": node_id,
            "type": workflow_type,
            "inputs": inputs_of[node_id],
            "params": params,
            "status": status,
            "artifact": artifact,
            "attempts": attempts,
        }
        if "workflow_reason" in config:
            node["reason"] = config["workflow_reason"]
        label = raw.get("label")
        if isinstance(label, str) and label != node_id:
            node["label"] = label
        if include_position and isinstance(raw.get("position"), dict):
            node["position"] = copy.deepcopy(raw["position"])
        workflow_nodes.append(node)
    try:
        return create_workflow(workflow_nodes)
    except CapabilityError as exc:
        raise WorkflowAdapterError(str(exc)) from exc


# ── legacy canvas edge compatibility (warnings only) ─────────────────────────

# Mirrors oprim.canvas_edge_validate COMPATIBLE (the matrix
# hevi.canvas.validation.validate_graph enforces). The frontend
# canvas-rules.ts matrix differs slightly (it also allows
# script -> audio and video -> audio); this function reports
# against the backend matrix because that is what blocks execution.
_BACKEND_COMPATIBLE: frozenset[tuple[str, str]] = frozenset(
    {
        ("text", "image"),
        ("text", "video"),
        ("text", "audio"),
        ("text", "script"),
        ("image", "video"),
        ("image", "image"),
        ("image", "script"),
        ("audio", "video"),
        ("video", "video"),
        ("script", "image"),
        ("script", "video"),
    }
)


def _edge_compatible(from_type: str, to_type: str) -> bool:
    try:
        from oprim.canvas_edge_validate import canvas_edge_validate

        return bool(canvas_edge_validate(from_type=from_type, to_type=to_type))
    except Exception:
        return (from_type, to_type) in _BACKEND_COMPATIBLE


def canvas_edge_warnings(graph: Any) -> list[dict[str, Any]]:
    """Report graph edges the legacy canvas matrix would reject.

    Warnings only: the adapter never drops such an edge (see module
    docstring). Each item names the edge and both endpoint types so
    a caller can decide whether to run the graph through the
    existing ``ExecutorService`` (which will reject it) or through
    the adapter rerun path (which will not).
    """
    raw_nodes, raw_edges = _graph_nodes_edges(graph)
    node_types: dict[str, str] = {}
    for raw in raw_nodes:
        if isinstance(raw, dict) and isinstance(raw.get("node_id"), str):
            node_types[raw["node_id"]] = raw.get("node_type", "")
    warnings: list[dict[str, Any]] = []
    for raw_edge in raw_edges:
        if not isinstance(raw_edge, dict):
            continue
        src = raw_edge.get("from_node_id")
        dst = raw_edge.get("to_node_id")
        from_type = raw_edge.get("from_type") or node_types.get(src, "")
        to_type = raw_edge.get("to_type") or node_types.get(dst, "")
        if from_type and to_type and not _edge_compatible(from_type, to_type):
            warnings.append(
                {
                    "edge_id": raw_edge.get("edge_id"),
                    "from_node_id": src,
                    "to_node_id": dst,
                    "from_type": from_type,
                    "to_type": to_type,
                    "message": (
                        f"legacy canvas matrix rejects "
                        f"{from_type!r} -> {to_type!r}"
                    ),
                }
            )
    return warnings


# ── rerun semantics (adapter layer, delegating to canvas_workflow) ──────────


def _as_workflow(source: Any) -> dict[str, Any]:
    """Accept a workflow dict or a graph dict, return a workflow."""
    if isinstance(source, dict) and isinstance(source.get("nodes"), list):
        nodes = source["nodes"]
        if nodes and all(
            isinstance(n, dict) and "node_type" in n for n in nodes
        ):
            return graph_to_workflow(source)
        if nodes and all(
            isinstance(n, dict) and "type" in n for n in nodes
        ):
            return _normalize_workflow(source)
    if isinstance(source, dict) and "nodes_json" in source:
        return graph_to_workflow(source)
    _fail("rerun source must be a workflow dict or a graph dict")


def rerun_order(source: Any, selected_ids: Any) -> list[str]:
    """Topological execution list for ``selected_ids`` (deps first)."""
    workflow = _as_workflow(source)
    try:
        return _wf_rerun_selection(workflow, selected_ids)
    except CapabilityError as exc:
        raise WorkflowAdapterError(str(exc)) from exc


def plan_rerun(source: Any, selected_ids: Any) -> list[dict[str, Any]]:
    """Rerun plan: each item is ``{node_id, action, reason}``.

    ``action`` is ``run`` or ``skip``; a ``done`` node with an
    artifact is ``skip``/``already_done`` unless explicitly
    selected. Blocked nodes are not specially skipped here: a
    blocked node that is selected will fail loudly when its result
    is applied (see ``apply_run_result_to_graph``), matching the
    workflow model's rule that a blocked node accepts no runs.
    """
    workflow = _as_workflow(source)
    try:
        return _wf_plan_rerun(workflow, selected_ids)
    except CapabilityError as exc:
        raise WorkflowAdapterError(str(exc)) from exc


def apply_run_result_to_graph(
    graph: Any, node_id: str, status: str, *, artifact: Any = None
) -> dict[str, Any]:
    """Return a new graph with one node's run result applied.

    Positions (and any extra top-level graph keys such as ``name``)
    are preserved from the input graph; only the target node's
    config meta and frontend status change. A third failure moves
    the node to ``blocked`` and any further result for it raises,
    per the workflow model.
    """
    if not isinstance(graph, dict):
        _fail("graph must be a dict")
    raw_nodes, _ = _graph_nodes_edges(graph)
    positions = {
        n["node_id"]: copy.deepcopy(n["position"])
        for n in raw_nodes
        if isinstance(n, dict) and isinstance(n.get("position"), dict)
    }
    workflow = graph_to_workflow(graph)
    try:
        new_workflow = apply_run_result(
            workflow, node_id, status, artifact=artifact
        )
    except CapabilityError as exc:
        raise WorkflowAdapterError(str(exc)) from exc
    new_graph = workflow_to_graph(new_workflow, positions=positions)
    out = {k: copy.deepcopy(v) for k, v in graph.items()}
    out["nodes"] = new_graph["nodes"]
    out["edges"] = new_graph["edges"]
    if "nodes_json" in graph:
        out["nodes_json"] = new_graph["nodes"]
    if "edges_json" in graph:
        out["edges_json"] = new_graph["edges"]
    return out


def planned_graph(source: Any, selected_ids: Any) -> dict[str, Any]:
    """Graph containing only the rerun scope, in topological order.

    Includes both ``run`` and ``skip`` nodes: skip nodes are part
    of the scope (their artifacts are the inputs the run nodes
    depend on), even though a selective executor must not re-run
    them. Use ``plan_rerun`` alongside this to tell run from skip.
    """
    graph = workflow_to_graph(_as_workflow(source))
    order = rerun_order(source, selected_ids)
    wanted = set(order)
    nodes = [n for n in graph["nodes"] if n["node_id"] in wanted]
    nodes.sort(key=lambda n: order.index(n["node_id"]))
    edges = [
        e
        for e in graph["edges"]
        if e["from_node_id"] in wanted and e["to_node_id"] in wanted
    ]
    return {"nodes": nodes, "edges": edges}


def as_graph_service_payload(
    graph: Any, *, name: str = "Untitled", description: str = ""
) -> dict[str, Any]:
    """Shape a graph dict as ``GraphService.save_graph`` kwargs.

    Returns ``{"name", "description", "nodes", "edges"}``; pass it
    with ``user_id`` to ``save_graph``. This is the reuse seam to
    the existing persistence path: workflow graphs are stored
    exactly like hand-drawn canvas graphs.
    """
    nodes, edges = _graph_nodes_edges(graph)
    return {
        "name": name,
        "description": description,
        "nodes": copy.deepcopy(nodes),
        "edges": copy.deepcopy(edges),
    }


def run_preflight_for_workflow(
    workflow: Any, *, budget_usd: float | None = None,
    target_duration_s: float | None = None,
):
    """Run the existing canvas preflight on a workflow.

    Reuses ``hevi.canvas.preflight.run_preflight`` directly: the
    workflow is mapped to canvas nodes (validated as ``CanvasNode``)
    and the report is returned unchanged. Note the boundary quirk:
    ``assemble`` maps to a ``video`` canvas node, so preflight's
    video-only cost/duration accounting counts an assemble node as
    a video node (default 5s when no ``duration_s`` param is set).
    Imported lazily so importing this adapter stays light.
    """
    from oprim.hevi_types import CanvasNode

    from hevi.canvas.preflight import run_preflight

    graph = workflow_to_graph(workflow)
    nodes = [CanvasNode.model_validate(n) for n in graph["nodes"]]
    return run_preflight(
        nodes, budget_usd=budget_usd, target_duration_s=target_duration_s
    )
