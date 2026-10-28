"""Editable project graph (``pipeline.project_graph``).

This is the productization layer on top of ``pipeline.project_handoff``,
not a second canvas. ``canvas_workflow`` already owns the infinite
canvas DAG; this module owns the *project* view of that idea: the
manifest of a finished-film project, upgraded from a plain file list
to nodes plus edges plus reusable templates.

Node types (exactly these six; anything else is refused and named):

* ``storyboard`` -- the shot table for the film.
* ``first_frame`` -- a first-frame image for a shot.
* ``motion`` -- a moving clip generated from frames.
* ``narration`` -- a narration audio track.
* ``subtitle`` -- a subtitle track.
* ``cover`` -- a cover image.

Edges are always input -> output: a node's ``inputs`` list names the
node ids it consumes, so the edge list is derived, never hand-written
separately (a hand-written edge list could drift from the nodes).

Templates: a graph that has actually run to success may be saved as
a template. The template keeps the node types and the wiring, plus
the success record that proves the run happened. Rebinding a
template for new material only replaces node artifacts / params --
it never rewrites the wiring. A rebind that names an unknown node,
or that would change a node type or an input list, is refused.

Validation failures name the problem, not just a boolean:

* missing input -- a node lists an input id that is not a node;
* broken link -- same as missing input, reported per node (kept as a
  distinct problem kind so callers can tell a dangling edge from a
  cycle);
* cycle -- the input graph is not a DAG; the nodes on (or reachable
  into) the cycle are named.

Serialization: ``to_json`` / ``from_json`` round-trip exactly, and
loading re-validates. Replay is the topological order of the nodes:
every input runs before the node that consumes it.

Manifest integration: ``attach_graph_to_manifest`` stores the graph
under the ``graph`` key of an existing ``pipeline.project_handoff``
manifest (created by ``create_project``). It does not rewrite the
stage blocks, and it refuses a project whose manifest is missing.

Failure contract: unknown node type, duplicate node id, missing
input, broken link and cycle all raise ``CapabilityError`` from the
strict constructors (``create_graph`` / ``topological_order`` /
``rebind_template`` / ``save_template``). ``validate_graph`` is the
non-raising twin: it returns the same problems as data so a UI or a
gate can list them all at once.
"""

from __future__ import annotations

import copy
import json
import time
from pathlib import Path
from typing import Any

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

NODE_TYPES: tuple[str, ...] = (
    "storyboard",
    "first_frame",
    "motion",
    "narration",
    "subtitle",
    "cover",
)

_GRAPH_VERSION = 1


def _fail(message: str) -> None:
    raise CapabilityError(f"pipeline.project_graph: {message}")


def _require_str(value: Any, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail(f"{what} must be a non-empty string")
    return str(value).strip()


def _normalize_node(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        _fail(f"node is not an object: {raw!r}")
    node_id = _require_str(raw.get("node_id"), "node_id")
    node_type = raw.get("type")
    if node_type not in NODE_TYPES:
        _fail(
            f"node {node_id!r} has unknown type {node_type!r}; "
            f"known types: {list(NODE_TYPES)}"
        )
    inputs = raw.get("inputs", [])
    if not isinstance(inputs, list) or not all(
        isinstance(item, str) for item in inputs
    ):
        _fail(f"node {node_id!r}: inputs must be a list of node ids")
    params = raw.get("params", {})
    if not isinstance(params, dict):
        _fail(f"node {node_id!r}: params must be an object")
    artifact = raw.get("artifact")
    if artifact is not None and not isinstance(artifact, str):
        _fail(f"node {node_id!r}: artifact must be a string or null")
    return {
        "node_id": node_id,
        "type": node_type,
        "inputs": list(inputs),
        "params": copy.deepcopy(params),
        "artifact": artifact,
    }


def edges_of(graph: dict[str, Any]) -> list[dict[str, str]]:
    """Derive input -> output edges from node inputs."""
    nodes = graph.get("nodes", []) if isinstance(graph, dict) else []
    edges: list[dict[str, str]] = []
    for node in nodes:
        for source in node.get("inputs", []):
            edges.append({"from": source, "to": node["node_id"]})
    return edges


def validate_graph(graph: Any) -> dict[str, Any]:
    """Return {ok, problems} without raising.

    Problem kinds: ``duplicate_node``, ``unknown_type``,
    ``missing_input`` / ``broken_link``, ``cycle``.
    """
    problems: list[dict[str, Any]] = []
    if not isinstance(graph, dict) or not isinstance(graph.get("nodes"), list):
        return {
            "ok": False,
            "problems": [{
                "kind": "bad_graph",
                "detail": "graph must be an object with a nodes list",
            }],
        }
    nodes = graph["nodes"]
    seen: dict[str, dict[str, Any]] = {}
    for raw in nodes:
        if not isinstance(raw, dict) or not raw.get("node_id"):
            problems.append({
                "kind": "bad_node",
                "detail": f"node without node_id: {raw!r}",
            })
            continue
        node_id = raw["node_id"]
        if node_id in seen:
            problems.append({
                "kind": "duplicate_node",
                "node_id": node_id,
                "detail": f"duplicate node id {node_id!r}",
            })
            continue
        seen[node_id] = raw
        if raw.get("type") not in NODE_TYPES:
            problems.append({
                "kind": "unknown_type",
                "node_id": node_id,
                "detail": f"node {node_id!r} has unknown type {raw.get('type')!r}",
            })
        inputs = raw.get("inputs", [])
        if not isinstance(inputs, list):
            problems.append({
                "kind": "bad_inputs",
                "node_id": node_id,
                "detail": f"node {node_id!r}: inputs must be a list",
            })
            continue
        for source in inputs:
            if source not in seen and source not in {
                n.get("node_id") for n in nodes if isinstance(n, dict)
            }:
                problems.append({
                    "kind": "missing_input",
                    "node_id": node_id,
                    "missing_input": source,
                    "detail": (
                        f"node {node_id!r} lists missing input {source!r}; "
                        f"broken link: input is not a node in this graph"
                    ),
                })
    # Cycle check only when every input resolves; otherwise the
    # missing-input problems above are the actionable report.
    if not any(p["kind"] == "missing_input" for p in problems):
        try:
            topological_order({"nodes": [
                {"node_id": n["node_id"],
                 "type": n.get("type"),
                 "inputs": n.get("inputs", []),
                 "params": n.get("params", {}),
                 "artifact": n.get("artifact")}
                for n in nodes if isinstance(n, dict) and n.get("node_id")
            ]})
        except CapabilityError as exc:
            problems.append({
                "kind": "cycle",
                "detail": str(exc),
            })
    return {"ok": not problems, "problems": problems}


def create_graph(nodes: Any) -> dict[str, Any]:
    """Build and strictly validate a graph. Raises on any problem."""
    if not isinstance(nodes, list) or not nodes:
        _fail("graph needs at least one node (empty graph refused)")
    normalized = [_normalize_node(raw) for raw in nodes]
    ids = [n["node_id"] for n in normalized]
    if len(set(ids)) != len(ids):
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        _fail(f"duplicate node ids: {dupes}")
    id_set = set(ids)
    for node in normalized:
        for source in node["inputs"]:
            if source not in id_set:
                _fail(
                    f"node {node['node_id']!r} has missing input "
                    f"{source!r}; broken link: input is not a node "
                    f"in this graph"
                )
    graph = {"version": _GRAPH_VERSION, "nodes": normalized}
    # topological_order raises (naming the cycle) if there is one.
    topological_order(graph)
    return graph


def topological_order(graph: dict[str, Any]) -> list[str]:
    """Node ids with every input before its consumer. Raises on cycle."""
    nodes = graph.get("nodes", [])
    by_id = {n["node_id"]: n for n in nodes}
    order: list[str] = []
    state: dict[str, str] = {}

    def visit(node_id: str, stack: list[str]) -> None:
        mark = state.get(node_id)
        if mark == "done":
            return
        if mark == "visiting":
            cycle = stack[stack.index(node_id):] + [node_id]
            _fail(f"cycle detected among nodes: {cycle}")
        state[node_id] = "visiting"
        stack.append(node_id)
        for source in by_id[node_id].get("inputs", []):
            if source not in by_id:
                _fail(
                    f"node {node_id!r} has missing input {source!r}; "
                    f"broken link: input is not a node in this graph"
                )
            visit(source, stack)
        stack.pop()
        state[node_id] = "done"
        order.append(node_id)

    for node_id in by_id:
        visit(node_id, [])
    return order


def replay_order(graph: dict[str, Any]) -> list[str]:
    """Replay plan: the topological order, as node ids."""
    report = validate_graph(graph)
    if not report["ok"]:
        details = "; ".join(p["detail"] for p in report["problems"])
        _fail(f"graph is not replayable: {details}")
    return topological_order(graph)


def replay_nodes(graph: dict[str, Any]) -> list[dict[str, Any]]:
    """Replay plan: full node dicts in topological order."""
    order = replay_order(graph)
    by_id = {n["node_id"]: n for n in graph["nodes"]}
    return [copy.deepcopy(by_id[node_id]) for node_id in order]


def to_json(graph: dict[str, Any]) -> str:
    report = validate_graph(graph)
    if not report["ok"]:
        details = "; ".join(p["detail"] for p in report["problems"])
        _fail(f"graph is not serializable: {details}")
    return json.dumps(graph, ensure_ascii=False, indent=2, sort_keys=True)


def from_json(text: Any) -> dict[str, Any]:
    if not isinstance(text, str):
        _fail("from_json needs a JSON string")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        _fail(f"graph JSON is not valid JSON: {exc}")
    if not isinstance(data, dict) or "nodes" not in data:
        _fail("graph JSON has no nodes list")
    # Re-validate strictly: unknown types / duplicates / missing
    # inputs / cycles are all refused here, not silently loaded.
    return create_graph(data["nodes"])


def save_template(
    graph: dict[str, Any],
    template_id: str,
    success_record: dict[str, Any],
) -> dict[str, Any]:
    """Save a *proven* graph as a reusable template.

    ``success_record`` must prove a real run: a non-empty ``run_id``
    and a ``status`` of ``success`` (``ok`` is accepted as the same
    word). Anything else is refused -- an unproven chain is not a
    template, it is a draft.
    """
    template_id = _require_str(template_id, "template_id")
    if not isinstance(success_record, dict):
        _fail("save_template: success_record must be an object")
    run_id = success_record.get("run_id")
    status = success_record.get("status")
    if not run_id or status not in ("success", "ok"):
        _fail(
            "save_template: template requires a success record "
            f"(run_id non-empty, status 'success'); got run_id={run_id!r} "
            f"status={status!r}; an unproven graph cannot be templated"
        )
    clean = create_graph(copy.deepcopy(graph.get("nodes", [])))
    return {
        "template_id": template_id,
        "version": _GRAPH_VERSION,
        "nodes": clean["nodes"],
        "edges": edges_of(clean),
        "success_record": copy.deepcopy(success_record),
        "saved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def rebind_template(
    template: dict[str, Any],
    bindings: dict[str, Any],
) -> dict[str, Any]:
    """Rebind a template to new material without rewriting the wiring.

    ``bindings`` maps a node id to either a new artifact string or an
    object ``{"artifact": ..., "params": {...}}`` (params are merged).
    Node types and input lists are copied verbatim from the template;
    any binding for an unknown node, or any attempt to change a type
    or an input list (bindings carry no such fields, so this is
    enforced structurally), is refused.
    """
    if not isinstance(template, dict) or not isinstance(
        template.get("nodes"), list
    ):
        _fail("rebind_template: template has no nodes list")
    if not isinstance(bindings, dict):
        _fail("rebind_template: bindings must be an object")
    known = {n["node_id"] for n in template["nodes"]}
    unknown = sorted(set(bindings) - known)
    if unknown:
        _fail(f"rebind_template: unknown node ids in bindings: {unknown}")
    nodes: list[dict[str, Any]] = []
    for node in template["nodes"]:
        new_node = copy.deepcopy(node)
        if node["node_id"] in bindings:
            binding = bindings[node["node_id"]]
            if isinstance(binding, str):
                new_node["artifact"] = binding
            elif isinstance(binding, dict):
                if "artifact" in binding:
                    new_node["artifact"] = binding["artifact"]
                if "params" in binding:
                    if not isinstance(binding["params"], dict):
                        _fail(
                            "rebind_template: params binding for "
                            f"{node['node_id']!r} must be an object"
                        )
                    merged = dict(new_node.get("params", {}))
                    merged.update(binding["params"])
                    new_node["params"] = merged
            else:
                _fail(
                    "rebind_template: binding for "
                    f"{node['node_id']!r} must be an artifact string "
                    "or an object"
                )
        nodes.append(new_node)
    graph = create_graph(nodes)
    return {
        "template_id": template.get("template_id"),
        "version": _GRAPH_VERSION,
        "nodes": graph["nodes"],
        "edges": edges_of(graph),
        "replay_order": topological_order(graph),
        "rebound_nodes": sorted(bindings),
    }


def attach_graph_to_manifest(
    project_root: Path, graph: dict[str, Any]
) -> dict[str, Any]:
    """Store a validated graph (and its replay order) in a manifest."""
    root = Path(project_root)
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        _fail(
            f"manifest not found: {manifest_path} "
            "(run pipeline.project_handoff create first)"
        )
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        _fail(f"manifest is not valid JSON: {manifest_path}")
    clean = create_graph(copy.deepcopy(graph.get("nodes", [])))
    # Preserve a references mapping table if the caller attached one
    # (see pipeline.smart_reference); it travels with the graph.
    if isinstance(graph, dict) and "references" in graph:
        clean["references"] = copy.deepcopy(graph["references"])
    data["graph"] = clean
    data["graph_replay_order"] = topological_order(clean)
    manifest_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return data


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
             aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    action = params.get("action", "validate")
    nodes = params.get("nodes", [])
    if action == "create":
        result: dict[str, Any] = {
            "capability": "pipeline.project_graph",
            "graph": create_graph(nodes),
        }
        result["replay_order"] = topological_order(result["graph"])
    elif action == "validate":
        result = {
            "capability": "pipeline.project_graph",
            **validate_graph({"nodes": nodes}),
        }
    elif action == "replay":
        graph = create_graph(nodes)
        result = {
            "capability": "pipeline.project_graph",
            "replay_order": replay_order(graph),
            "nodes": replay_nodes(graph),
        }
    elif action == "template":
        result = {
            "capability": "pipeline.project_graph",
            "template": save_template(
                {"nodes": nodes},
                str(params.get("template_id", "")),
                dict(params.get("success_record", {})),
            ),
        }
    elif action == "rebind":
        result = {
            "capability": "pipeline.project_graph",
            "graph": rebind_template(
                dict(params.get("template", {})),
                dict(params.get("bindings", {})),
            ),
        }
    else:
        _fail(
            f"unknown action {action!r}; known: create, validate, "
            "replay, template, rebind"
        )
    report_path = out_dir / "project_graph_report.json"
    report_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "result": result},
    )


def register_project_graph_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="pipeline.project_graph",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": [
                        "create", "validate", "replay", "template",
                        "rebind"]},
                    "nodes": {"type": "array", "items": {"type": "object"}},
                    "template_id": {"type": "string"},
                    "success_record": {"type": "object"},
                    "template": {"type": "object"},
                    "bindings": {"type": "object"},
                },
                "required": [],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Editable project graph on top of pipeline.project_handoff: "
                "storyboard/first_frame/motion/narration/subtitle/cover "
                "nodes with input->output edges derived from inputs, "
                "JSON serialization, topological replay, validation that "
                "names missing inputs, broken links and cycles, and "
                "success-recorded templates rebindable to new material "
                "without rewriting the wiring. No canvas is duplicated: "
                "canvas_workflow owns the canvas DAG; this owns the "
                "project manifest view."
            ),
            line="pipeline",
        )
    )
    return ["pipeline.project_graph"]


register_project_graph_capabilities_once()
