"""Canvas workflow model -- ``canvas_workflow``.

A serializable, re-runnable workflow specification for the hevi
pipeline, with no frontend and no generation of its own. A workflow is
a plain dict ``{"nodes": [...]}`` whose nodes form a directed acyclic
graph (DAG): each node names its upstream dependencies, and execution
always walks dependencies first.

Node types line up with the pipeline stages used by the sibling
capabilities (script, storyboard frames, video, sound, subtitles,
assembly):

* ``script`` -- screenplay / episode script stage.
* ``first_frame`` -- first-frame image for a shot.
* ``tail_frame`` -- tail-frame image for a shot.
* ``video`` -- moving clip generated from frames.
* ``audio`` -- sound layer (dialogue / music / effects).
* ``subtitle`` -- subtitle track.
* ``assemble`` -- final assembly / edit step.

A node is a dict with these fields:

* ``node_id`` (str, required): unique within the workflow.
* ``type`` (str, required): one of the fixed types above.
* ``inputs`` (list of node_id, default []): upstream nodes.
* ``params`` (dict, default {}): caller-supplied parameters.
* ``status`` (str, default ``"pending"``): one of ``pending``,
  ``done``, ``failed``, ``blocked``.
* ``artifact`` (str or None, default None): finished output reference.
* ``attempts`` (int, default 0): number of failed runs so far.

Rules enforced here, in own wording and with no external behaviour:

* A workflow is rejected when it is empty, repeats a node_id, uses
  an unknown type, references an unknown upstream node, or contains
  a cycle (including a node that lists itself as an input).
* ``rerun_selection`` returns the selected nodes plus every upstream
  dependency, in topological order, each node exactly once.
* A failed node may be retried at most three times: the first two
  failures keep it ``failed``, the third failure moves it to
  ``blocked`` with ``reason="max_retries_exceeded"``, and a blocked
  node accepts no further run results.
* ``plan_rerun`` is idempotent by default: a ``done`` node with a
  non-empty artifact is skipped unless it was explicitly selected.
* Workflows round-trip through JSON exactly (``sort_keys=True``),
  and loading JSON re-validates the whole structure.

This module uses only the standard library, makes no network or
generation calls, and never mutates a workflow handed to it: every
function that reports a changed workflow returns a new dict.
"""

from __future__ import annotations

import copy
import json
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

NODE_TYPES = frozenset(
    {
        "script",
        "first_frame",
        "tail_frame",
        "video",
        "audio",
        "subtitle",
        "assemble",
    }
)

NODE_STATUSES = frozenset({"pending", "done", "failed", "blocked"})

MAX_ATTEMPTS = 3

BLOCKED_REASON = "max_retries_exceeded"

__all__ = [
    "NODE_TYPES",
    "NODE_STATUSES",
    "MAX_ATTEMPTS",
    "BLOCKED_REASON",
    "create_workflow",
    "rerun_selection",
    "apply_run_result",
    "plan_rerun",
    "to_json",
    "from_json",
]


def _fail(message: str) -> None:
    raise CapabilityError(message)


def _normalize_node(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        _fail("workflow node must be a dict")
    node_id = raw.get("node_id")
    if not isinstance(node_id, str) or not node_id:
        _fail("workflow node requires a non-empty string node_id")
    node_type = raw.get("type")
    if node_type not in NODE_TYPES:
        _fail(f"unknown node type for node {node_id!r}: {node_type!r}")
    inputs = raw.get("inputs", [])
    if not isinstance(inputs, list) or any(
        not isinstance(item, str) for item in inputs
    ):
        _fail(f"node {node_id!r} inputs must be a list of node_id strings")
    params = raw.get("params", {})
    if not isinstance(params, dict):
        _fail(f"node {node_id!r} params must be a dict")
    status = raw.get("status", "pending")
    if status not in NODE_STATUSES:
        _fail(f"node {node_id!r} has unknown status: {status!r}")
    artifact = raw.get("artifact", None)
    if artifact is not None and not isinstance(artifact, str):
        _fail(f"node {node_id!r} artifact must be a string or None")
    attempts = raw.get("attempts", 0)
    if isinstance(attempts, bool) or not isinstance(attempts, int) or attempts < 0:
        _fail(f"node {node_id!r} attempts must be a non-negative int")
    node = copy.deepcopy(raw)
    node["node_id"] = node_id
    node["type"] = node_type
    node["inputs"] = list(inputs)
    node["params"] = params
    node["status"] = status
    node["artifact"] = artifact
    node["attempts"] = attempts
    return node


def _check_acyclic(nodes: list[dict[str, Any]]) -> None:
    by_id = {node["node_id"]: node for node in nodes}
    state: dict[str, str] = {}

    def visit(node_id: str) -> None:
        mark = state.get(node_id)
        if mark == "done":
            return
        if mark == "visiting":
            _fail(f"workflow inputs contain a cycle through node {node_id!r}")
        state[node_id] = "visiting"
        for upstream in by_id[node_id]["inputs"]:
            visit(upstream)
        state[node_id] = "done"

    for node in nodes:
        visit(node["node_id"])


def create_workflow(nodes: Any) -> dict[str, Any]:
    """Validate ``nodes`` and return ``{"nodes": [...]}`` in caller order.

    Missing optional fields are filled with their defaults. The input
    list is deep-copied, so later caller mutation cannot change the
    returned workflow. Raises :class:`CapabilityError` for an empty
    list, a duplicate node_id, an unknown type, an unknown input
    reference, or a cycle (including self-reference).
    """
    if not isinstance(nodes, list) or not nodes:
        _fail("workflow nodes must be a non-empty list")
    normalized = [_normalize_node(raw) for raw in nodes]
    seen: set[str] = set()
    for node in normalized:
        if node["node_id"] in seen:
            _fail(f"duplicate node_id: {node['node_id']!r}")
        seen.add(node["node_id"])
    for node in normalized:
        for upstream in node["inputs"]:
            if upstream not in seen:
                _fail(
                    f"node {node['node_id']!r} inputs unknown node {upstream!r}"
                )
    _check_acyclic(normalized)
    return {"nodes": normalized}


def _nodes_of(workflow: Any) -> list[dict[str, Any]]:
    if not isinstance(workflow, dict) or not isinstance(
        workflow.get("nodes"), list
    ):
        _fail("workflow must be a dict with a nodes list")
    return workflow["nodes"]


def _by_id(workflow: Any) -> dict[str, dict[str, Any]]:
    nodes = _nodes_of(workflow)
    by_id: dict[str, dict[str, Any]] = {}
    for node in nodes:
        if not isinstance(node, dict) or not isinstance(
            node.get("node_id"), str
        ):
            _fail("workflow node must be a dict with a string node_id")
        by_id[node["node_id"]] = node
    return by_id


def rerun_selection(workflow: Any, selected_ids: Any) -> list[str]:
    """Return the topological execution list for ``selected_ids``.

    The list contains every selected node plus all of its upstream
    dependencies (even when a dependency was not selected), with
    dependencies before the nodes that depend on them, each node once.
    Raises :class:`CapabilityError` for a selected id that does not
    exist in the workflow.
    """
    by_id = _by_id(workflow)
    if not isinstance(selected_ids, (list, tuple)):
        _fail("selected_ids must be a list of node_id strings")
    for selected in selected_ids:
        if selected not in by_id:
            _fail(f"selected node does not exist: {selected!r}")
    ordered: list[str] = []
    emitted: set[str] = set()

    def visit(node_id: str) -> None:
        if node_id in emitted:
            return
        emitted.add(node_id)
        for upstream in by_id[node_id].get("inputs", []):
            visit(upstream)
        ordered.append(node_id)

    for selected in selected_ids:
        visit(selected)
    return ordered


def apply_run_result(
    workflow: Any, node_id: str, status: str, *, artifact: Any = None
) -> dict[str, Any]:
    """Return a new workflow with one node's run result applied.

    The input workflow is never mutated. ``status`` must be ``done``
    or ``failed``. A ``done`` result keeps ``attempts`` unchanged and
    updates ``artifact`` to the passed value (which may be None). A
    ``failed`` result increments ``attempts``; when ``attempts``
    reaches 3 the node becomes ``blocked`` with
    ``reason="max_retries_exceeded"``. Any further call for a blocked
    node raises :class:`CapabilityError`, as does an unknown node_id
    or any status other than ``done`` / ``failed``.
    """
    by_id = _by_id(workflow)
    if node_id not in by_id:
        _fail(f"unknown node: {node_id!r}")
    current = by_id[node_id]
    if current.get("status") == "blocked":
        _fail(f"node {node_id!r} is blocked and accepts no further runs")
    if status not in ("done", "failed"):
        _fail(f"run result status must be done or failed, got {status!r}")
    if artifact is not None and not isinstance(artifact, str):
        _fail("run result artifact must be a string or None")
    new_workflow = copy.deepcopy(workflow)
    new_by_id = {node["node_id"]: node for node in new_workflow["nodes"]}
    target = new_by_id[node_id]
    if status == "done":
        target["status"] = "done"
        target["artifact"] = artifact
        target.pop("reason", None)
    else:
        attempts = target.get("attempts", 0) + 1
        target["attempts"] = attempts
        if attempts >= MAX_ATTEMPTS:
            target["status"] = "blocked"
            target["reason"] = BLOCKED_REASON
        else:
            target["status"] = "failed"
    return new_workflow


def plan_rerun(workflow: Any, selected_ids: Any) -> list[dict[str, Any]]:
    """Return the rerun plan for ``selected_ids`` in topological order.

    Each item is ``{"node_id", "action", "reason"}``. A node that is
    ``done`` with a non-empty artifact is marked ``skip`` /
    ``already_done``, unless it was explicitly selected, in which
    case it is marked ``run`` / ``selected``. Every other node is
    marked ``run``, with reason ``selected`` when explicitly selected
    and ``dependency`` otherwise.
    """
    ordered = rerun_selection(workflow, selected_ids)
    by_id = _by_id(workflow)
    selected = set(selected_ids)
    plan: list[dict[str, Any]] = []
    for node_id in ordered:
        node = by_id[node_id]
        if node_id in selected:
            plan.append(
                {"node_id": node_id, "action": "run", "reason": "selected"}
            )
        elif node.get("status") == "done" and node.get("artifact"):
            plan.append(
                {
                    "node_id": node_id,
                    "action": "skip",
                    "reason": "already_done",
                }
            )
        else:
            plan.append(
                {"node_id": node_id, "action": "run", "reason": "dependency"}
            )
    return plan


def to_json(workflow: Any) -> str:
    """Serialize ``workflow`` to a JSON string (``sort_keys=True``)."""
    try:
        return json.dumps(workflow, sort_keys=True, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise CapabilityError(f"workflow is not JSON-serializable: {exc}") from exc


def from_json(text: Any) -> dict[str, Any]:
    """Parse ``text`` and return a validated workflow.

    The parsed structure is re-validated through
    :func:`create_workflow`; any malformed JSON or illegal structure
    raises :class:`CapabilityError`.
    """
    if not isinstance(text, str):
        _fail("from_json input must be a JSON string")
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, ValueError) as exc:
        raise CapabilityError(f"invalid workflow JSON: {exc}") from exc
    if not isinstance(parsed, dict) or not isinstance(
        parsed.get("nodes"), list
    ):
        _fail("workflow JSON must be an object with a nodes list")
    return create_workflow(parsed["nodes"])


_PARAMS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "nodes": {"type": "array"},
        "selected_ids": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["nodes"],
    "additionalProperties": False,
}


def _write_report(out_dir: Path, payload: dict[str, Any]) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    report = out_dir / "canvas_workflow.json"
    report.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _render(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    # Report capability: this registers the workflow MODEL only (S-02 /
    # M-03).  It never executes anything: execution is a service-layer
    # behaviour and goes through POST /canvas/workflow-execute, which
    # delegates to ExecutorService (M-14).  Aspect is declared but
    # ignored (S-03).
    workflow = create_workflow(params["nodes"])
    payload: dict[str, Any] = {
        **workflow,
        "node_count": len(workflow["nodes"]),
    }
    selected = params.get("selected_ids")
    if selected is not None:
        payload["rerun_order"] = rerun_selection(workflow, selected)
        payload["rerun_plan"] = plan_rerun(workflow, selected)
    report = _write_report(Path(out_dir), payload)
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report),
        qa={"report_json": str(report), **payload},
    )


def register_canvas_workflow_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="story.canvas_workflow",
            kind="line",
            aspects=["16:9", "9:16", "1:1"],
            params_schema=_PARAMS_SCHEMA,
            cpu_cost_hint=0.0,
            render=_render,
            description=(
                "画布工作流模型：校验并落盘一个可重跑的 DAG 工作流"
                "（script/first_frame/tail_frame/video/audio/subtitle/"
                "assemble 节点，拓扑重跑规划、3 次失败封顶）。本能力"
                "只注册模型、不执行；执行走 POST /canvas/workflow-"
                "execute（委托 ExecutorService）。报告类能力：产物为"
                " workflow JSON（aspects 仅声明，渲染忽略）。"
            ),
            line="canvas_workflow",
            has_media_output=False,
        )
    )
    return ["story.canvas_workflow"]


register_canvas_workflow_capabilities_once()
