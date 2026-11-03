"""Canvas execution scheduling discipline
(``pipeline.canvas_execution_schedule``).

Clean-room rewrite of the execution-scheduling discipline from
``raph651/open-source-canvas`` (MIT; see
OPEN_SOURCE_CANVAS_ATTRIBUTION.md). No code, text or configuration
from that repository is copied here, and nothing here submits a
job, opens a network connection, or generates media: this module
only produces and judges *execution plans* for a DAG workflow.

It builds on ``canvas_workflow`` and never redefines its rules:
the workflow is validated by :func:`canvas_workflow.create_workflow`
(cycle, duplicate id, unknown type/upstream all rejected there),
and the retry ceiling is the single parameter already defined by
that module (``MAX_ATTEMPTS``). This module adds the scheduling
layer the DAG contract does not have:

1. Ready batches. Nodes are grouped by dependency depth and
   chunked into batches of at most ``max_parallel`` (default 2);
   a batch only runs once every upstream batch is done.
2. Upstream-failure skip. A node whose transitive upstream
   failed is marked ``skipped`` (reason ``upstream_failed``) and
   is never scheduled; failures are not retried by this layer --
   retry bookkeeping stays with ``canvas_workflow.apply_run_result``
   and its single ceiling.
3. Cancel discipline. Cancelling a plan marks its unscheduled
   nodes ``cancelled`` and records the single interrupt action
   (``POST /interrupt``); it performs no cancellation itself.
4. Seed batches. One batch count expands to one task per seed
   (``base_seed + index``); counts outside 1..4 fail.

Retry policy is a single source of truth: the caller may pass
``max_attempts`` only when it equals ``MAX_ATTEMPTS``, and no
node parameter may name a different retry ceiling. Any second
value fails with ``retry_policy_conflict`` instead of silently
winning.

Failure contract: a malformed workflow or an illegal parameter
raises :class:`CapabilityError`. Scheduling failures (retry
conflict, illegal seed count) are reported in the result, never
raised. Verdicts are ``pass`` / ``fail`` only.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hevi.capabilities.canvas_workflow import (
    MAX_ATTEMPTS,
    create_workflow,
    rerun_selection,
)
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

DEFAULT_MAX_PARALLEL = 2
MIN_SEED_BATCH = 1
MAX_SEED_BATCH = 4

_RETRY_PARAM_KEYS = ("max_retries", "max_attempts", "retries")

__all__ = [
    "DEFAULT_MAX_PARALLEL",
    "plan_canvas_execution",
    "resolve_execution_results",
    "cancel_execution",
    "expand_seed_batch",
]


def _fail(message: str) -> None:
    raise CapabilityError(message)


def _levels(nodes: list[dict[str, Any]]) -> dict[str, int]:
    by_id = {node["node_id"]: node for node in nodes}
    levels: dict[str, int] = {}

    def level(node_id: str, seen: frozenset[str]) -> int:
        if node_id in levels:
            return levels[node_id]
        if node_id in seen:  # unreachable: create_workflow rejects cycles
            _fail(f"workflow cycle involving {node_id!r}")
        inputs = by_id[node_id].get("inputs", [])
        depth = 0
        if inputs:
            depth = 1 + max(level(up, seen | {node_id}) for up in inputs)
        levels[node_id] = depth
        return depth

    for node in nodes:
        level(node["node_id"], frozenset())
    return levels


def _check_retry_policy(
    workflow: dict[str, Any], max_attempts: Any
) -> tuple[int, list[dict[str, str]]]:
    """Resolve the single retry ceiling; conflicts are failures."""
    failures: list[dict[str, str]] = []
    if max_attempts is None:
        resolved = MAX_ATTEMPTS
    else:
        if not isinstance(max_attempts, int) or isinstance(max_attempts, bool):
            _fail("max_attempts must be an integer")
        resolved = max_attempts
        if resolved != MAX_ATTEMPTS:
            failures.append(
                {
                    "code": "retry_policy_conflict",
                    "message": (
                        f"max_attempts {resolved} conflicts with the "
                        f"single retry ceiling {MAX_ATTEMPTS} defined "
                        "by canvas_workflow; retry policy must be "
                        "declared in exactly one place"
                    ),
                }
            )
    for node in workflow["nodes"]:
        params = node.get("params", {})
        if not isinstance(params, dict):
            continue
        for key in _RETRY_PARAM_KEYS:
            if key in params and params[key] != MAX_ATTEMPTS:
                failures.append(
                    {
                        "code": "retry_policy_conflict",
                        "message": (
                            f"node {node['node_id']!r} declares "
                            f"{key}={params[key]!r}, conflicting with "
                            f"the single retry ceiling {MAX_ATTEMPTS}"
                        ),
                    }
                )
    return resolved, failures


def expand_seed_batch(
    node_id: str, base_seed: int, count: int
) -> list[dict[str, Any]]:
    """Expand one seed batch into one task per seed.

    Counts outside 1..4 fail. This is plan arithmetic only: no
    task is submitted.
    """
    if not isinstance(node_id, str) or not node_id:
        _fail("seed batch node_id must be a non-empty string")
    if not isinstance(base_seed, int) or isinstance(base_seed, bool):
        _fail("seed batch base_seed must be an integer")
    if not isinstance(count, int) or isinstance(count, bool):
        _fail("seed batch count must be an integer")
    if count < MIN_SEED_BATCH or count > MAX_SEED_BATCH:
        _fail(
            f"seed batch count {count} is outside "
            f"{MIN_SEED_BATCH}..{MAX_SEED_BATCH}"
        )
    return [
        {
            "task_id": f"{node_id}:seed:{base_seed + index}",
            "node_id": node_id,
            "seed": base_seed + index,
        }
        for index in range(count)
    ]


def plan_canvas_execution(
    workflow: Any,
    *,
    max_parallel: int = DEFAULT_MAX_PARALLEL,
    max_attempts: Any = None,
    seed_batches: Any = None,
) -> dict[str, Any]:
    """Return the ready-batch execution plan for a DAG workflow.

    ``seed_batches`` maps a node id to ``{"base_seed": int,
    "count": int}``. The plan is a plain dict; nothing is
    executed.
    """
    validated = create_workflow(workflow["nodes"] if isinstance(workflow, dict) else workflow)
    if not isinstance(max_parallel, int) or isinstance(max_parallel, bool):
        _fail("max_parallel must be an integer")
    if max_parallel < 1:
        _fail("max_parallel must be at least 1")

    resolved_attempts, failures = _check_retry_policy(validated, max_attempts)

    seed_tasks: list[dict[str, Any]] = []
    tasks_by_node: dict[str, list[str]] = {}
    if seed_batches is not None:
        if not isinstance(seed_batches, dict):
            _fail("seed_batches must be an object mapping node_id to a batch")
        known = {node["node_id"] for node in validated["nodes"]}
        for node_id, spec in seed_batches.items():
            if node_id not in known:
                failures.append(
                    {
                        "code": "unknown_node",
                        "message": f"seed batch names unknown node {node_id!r}",
                    }
                )
                continue
            if not isinstance(spec, dict):
                _fail(f"seed batch for node {node_id!r} must be an object")
            try:
                tasks = expand_seed_batch(
                    node_id, spec.get("base_seed"), spec.get("count")
                )
            except CapabilityError as exc:
                failures.append({"code": "seed_batch_invalid", "message": str(exc)})
                continue
            tasks_by_node[node_id] = [task["task_id"] for task in tasks]
            seed_tasks.extend(tasks)

    if failures:
        return {
            "verdict": "fail",
            "node_count": len(validated["nodes"]),
            "max_parallel": max_parallel,
            "max_attempts": resolved_attempts,
            "batches": [],
            "seed_tasks": seed_tasks,
            "failures": failures,
        }

    topo = rerun_selection(
        validated, [node["node_id"] for node in validated["nodes"]]
    )
    levels = _levels(validated["nodes"])
    by_depth: dict[int, list[str]] = {}
    for node_id in topo:
        by_depth.setdefault(levels[node_id], []).append(node_id)
    batches: list[dict[str, Any]] = []
    for depth in sorted(by_depth):
        ready = by_depth[depth]
        for start in range(0, len(ready), max_parallel):
            chunk = ready[start : start + max_parallel]
            batches.append(
                {
                    "batch_index": len(batches),
                    "depth": depth,
                    "node_ids": chunk,
                    "tasks": [
                        task_id
                        for node_id in chunk
                        for task_id in tasks_by_node.get(node_id, [])
                    ],
                    "action": "run",
                }
            )
    return {
        "verdict": "pass",
        "node_count": len(validated["nodes"]),
        "max_parallel": max_parallel,
        "max_attempts": resolved_attempts,
        "batches": batches,
        "seed_tasks": seed_tasks,
        "failures": [],
    }


def resolve_execution_results(
    workflow: Any, results: Any
) -> dict[str, dict[str, str]]:
    """Resolve one round of run results to per-node dispositions.

    ``results`` maps node ids to ``"done"`` or ``"failed"``. A
    node with a failed transitive upstream is ``skipped``
    (reason ``upstream_failed``) and is never scheduled, whatever
    its own result says. Nodes with no result stay ``pending``.
    Retry bookkeeping is not done here; it belongs to
    ``canvas_workflow.apply_run_result``.
    """
    validated = create_workflow(workflow["nodes"] if isinstance(workflow, dict) else workflow)
    if not isinstance(results, dict):
        _fail("execution results must be an object mapping node_id to a status")
    known = {node["node_id"] for node in validated["nodes"]}
    for node_id, status in results.items():
        if node_id not in known:
            _fail(f"execution result names unknown node {node_id!r}")
        if status not in ("done", "failed"):
            _fail(
                f"execution result status must be done or failed, got {status!r}"
            )
    by_id = {node["node_id"]: node for node in validated["nodes"]}
    failed_upstream: set[str] = set()

    def upstream_failed(node_id: str, seen: frozenset[str]) -> bool:
        for upstream in by_id[node_id].get("inputs", []):
            if results.get(upstream) == "failed" or upstream in failed_upstream:
                return True
            if upstream not in seen and upstream_failed(upstream, seen | {node_id}):
                return True
        return False

    dispositions: dict[str, dict[str, str]] = {}
    for node in validated["nodes"]:
        node_id = node["node_id"]
        if upstream_failed(node_id, frozenset()):
            failed_upstream.add(node_id)
            dispositions[node_id] = {
                "disposition": "skipped",
                "reason": "upstream_failed",
            }
        elif results.get(node_id) == "done":
            dispositions[node_id] = {"disposition": "done", "reason": "reported"}
        elif results.get(node_id) == "failed":
            dispositions[node_id] = {"disposition": "failed", "reason": "reported"}
        else:
            dispositions[node_id] = {"disposition": "pending", "reason": "no_result"}
    return dispositions


def cancel_execution(
    plan: Any, *, node_ids: Any = None
) -> dict[str, Any]:
    """Record cancellation of a plan. Plan-only: no interrupt is sent.

    Every batch node in the plan (optionally restricted to
    ``node_ids``) is listed as cancelled and the single interrupt
    action (``POST /interrupt``) is recorded for the executor to
    perform. The plan itself carries no done state, so the
    executor must not cancel nodes it already knows are done;
    ``performed`` is always False here.
    """
    if not isinstance(plan, dict) or not isinstance(plan.get("batches"), list):
        _fail("cancel_execution needs an execution plan with batches")
    selected = None
    if node_ids is not None:
        selected = {str(node_id) for node_id in node_ids}
    cancelled: list[str] = []
    untouched: list[str] = []
    for batch in plan["batches"]:
        for node_id in batch.get("node_ids", []):
            if selected is not None and node_id not in selected:
                continue
            cancelled.append(node_id)
    return {
        "cancelled": cancelled,
        "untouched": untouched,
        "interrupt_action": "POST /interrupt",
        "performed": False,
    }


_PARAMS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "nodes": {"type": "array"},
        "max_parallel": {"type": "integer"},
        "max_attempts": {"type": "integer"},
        "seed_batches": {"type": "object"},
        "results": {"type": "object"},
    },
    "required": ["nodes"],
    "additionalProperties": False,
}


def _render(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    plan = plan_canvas_execution(
        {"nodes": params["nodes"]},
        max_parallel=int(params.get("max_parallel", DEFAULT_MAX_PARALLEL)),
        max_attempts=params.get("max_attempts"),
        seed_batches=params.get("seed_batches"),
    )
    report: dict[str, Any] = {"plan": plan}
    if params.get("results") is not None:
        report["dispositions"] = resolve_execution_results(
            {"nodes": params["nodes"]}, params["results"]
        )
    report_path = out_dir / "canvas_execution_schedule_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={
            "report_json": str(report_path),
            "verdict": plan["verdict"],
            "pass": plan["verdict"] == "pass",
            "failures": plan["failures"],
            **report,
        },
    )


def register_canvas_execution_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="pipeline.canvas_execution_schedule",
            kind="line",
            aspects=["16:9", "9:16", "1:1"],
            params_schema=_PARAMS_SCHEMA,
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Canvas execution scheduling: ready batches capped "
                "at a configurable parallel limit, upstream-failure "
                "skip, interrupt-based cancel discipline and one "
                "task per seed. Retry policy is the single ceiling "
                "defined by canvas_workflow. Plan only; nothing is "
                "submitted or executed."
            ),
            line="pipeline",
        )
    )
    return ["pipeline.canvas_execution_schedule"]


register_canvas_execution_capabilities_once()
