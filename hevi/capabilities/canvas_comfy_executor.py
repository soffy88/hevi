"""Canvas to ComfyUI executor (``pipeline.canvas_comfy_executor``).

Clean-room rewrite of the "canvas runs a ComfyUI workflow" execution
discipline from ``raph651/open-source-canvas`` (MIT; see
OPEN_SOURCE_CANVAS_ATTRIBUTION.md). No code, text, configuration or
workflow JSON from that repository is copied here. This module is
the execution layer the P0 grafts deliberately did not build: it
translates ``canvas_workflow`` DAG ``video`` nodes into ComfyUI API
graphs and submits them over HTTP, after the two P0 gates, and
polls the result. It reuses, and never redefines:

* ``canvas_workflow`` for DAG validation, the single retry ceiling
  and run-result bookkeeping (``create_workflow`` /
  ``apply_run_result``);
* ``canvas_execution_schedule`` for ready batches, seed-batch
  expansion and the single retry ceiling;
* ``comfy_gateway_contract`` for the six-endpoint allowlist that
  every request must pass before it is sent;
* ``model_install_gate`` for the pre-submit loader-visibility
  check, judged against a caller-supplied snapshot.

Execution discipline, in own wording:

1. Templates plus runtime injection. A ``video`` node names a
   template: either a caller-supplied API graph with an explicit
   ``inject`` list, or the built-in image template (core ComfyUI
   nodes only). Injection writes exactly the declared fields from
   exactly the declared sources (prompt, seed, width, height,
   checkpoint, frames, negative prompt, reference image) and
   fails, naming the node and field, when an injection target
   does not exist. Nothing is silently created or renamed.
2. Size snapping. Width and height are rounded to the 32 grid
   before injection, the same grid the upstream builder used.
   The six-section text format belongs to ``scene_reference``:
   six sections govern prompt *text* only; this builder governs
   graph *structure* only, and the two never share a definition.
3. Gates before submission. The gateway contract judges the
   planned ``POST /prompt`` (and the ``GET /history/<id>`` and
   ``POST /interrupt`` shapes the poll/cancel path will use), and
   the install gate judges the model record against the
   caller-supplied loader snapshot. Either failure refuses the
   whole run before anything is submitted. The snapshot is
   supplied out of band: the gateway allowlist refuses
   ``/object_info``, so this executor never fetches a snapshot
   through the gateway, and it never guesses file presence.
4. Polling. ``GET /history/<prompt_id>`` every 800 ms (the
   upstream interval) with a 10-minute timeout, both overridable
   by the caller. A 404 while polling means "still queued" and
   polling continues. A ComfyUI execution error is raised
   carrying the raw history text verbatim, never paraphrased.
   On timeout the executor best-effort posts ``/interrupt``
   before raising.
5. Upstream failure skips downstream. Batches run in plan
   order; a node whose transitive upstream failed is skipped,
   never submitted. Non-``video`` nodes are skipped, never
   translated: this executor only knows how to run video nodes.
   Seed batches submit one job per seed (``base_seed + index``).
6. No credential handling. The base URL and visitor id are
   caller-supplied; no key, secret or token value is read,
   stored or sent by this module.

Honest evidence limits -- read before claiming a generation:

* This executor has ONLY ever been exercised against a local
  fake ComfyUI server (see tests/test_canvas_comfy_executor.py).
  No real ComfyUI generation has been run through it: the local
  GPU is stopped, so no real ComfyUI run was possible, and no
  output file produced by this module may be described as a
  real generation. The built-in image template is a core-node
  graph shape, not a verified ComfyUI run.
* Deliberately NOT built here, with reasons: no collaboration
  room (upstream: in-memory, last-write-wins, unauthenticated,
  demo only -- unsuitable for multi-user production); no
  API-model wrappers (upstream's registry is empty; wrappers
  need keys plus a server-side proxy, and keys never enter
  this codebase); no MiniMax H3 workflow (H3 execution stays
  on the existing ``video.fasth3_local`` path with its locked
  workflow and weights); no 3D viewer chain (no browser
  capture chain exists in hevi, and the upstream repository
  has none either).
"""

from __future__ import annotations

import copy
import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

from hevi.capabilities.canvas_execution_schedule import plan_canvas_execution
from hevi.capabilities.canvas_workflow import (
    apply_run_result,
    create_workflow,
)
from hevi.capabilities.comfy_gateway_contract import check_gateway_request
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.model_install_gate import check_model_install
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

GRID = 32
DEFAULT_POLL_INTERVAL_S = 0.8
DEFAULT_TIMEOUT_S = 600.0
DEFAULT_VISITOR_ID = "canvas"

# Injection sources a template may declare. Anything else fails.
_INJECT_SOURCES = frozenset(
    {
        "prompt",
        "seed",
        "width",
        "height",
        "checkpoint",
        "frames",
        "negative_prompt",
        "ref_image",
    }
)

__all__ = [
    "GRID",
    "DEFAULT_POLL_INTERVAL_S",
    "DEFAULT_TIMEOUT_S",
    "snap_to_grid",
    "build_image_graph",
    "translate_video_node",
    "interrupt",
    "submit_and_poll",
    "execute_canvas_workflow",
]


def _fail(message: str) -> None:
    raise CapabilityError(message)


def snap_to_grid(value: Any, *, grid: int = GRID) -> int:
    """Round ``value`` to the nearest multiple of ``grid`` (default 32)."""
    if isinstance(value, bool) or not isinstance(value, int):
        _fail(f"size must be an integer, got {value!r}")
    if value <= 0:
        _fail(f"size must be positive, got {value!r}")
    if grid <= 0:
        _fail(f"grid must be positive, got {grid!r}")
    return int(round(value / grid)) * grid


def build_image_graph(
    *,
    prompt: str,
    seed: int,
    width: int,
    height: int,
    checkpoint: str,
    negative_prompt: str = "",
) -> dict[str, Any]:
    """Build the built-in core-node image graph (structure only).

    Core ComfyUI node classes only; steps/cfg/sampler are declared
    defaults, not measured values. This graph shape has never been
    run against a real ComfyUI server (see the module docstring):
    callers must run it once in ComfyUI and export the working
    API graph before treating it as verified.
    """
    if not isinstance(prompt, str) or not prompt.strip():
        _fail("image graph needs a non-empty prompt")
    if not isinstance(checkpoint, str) or not checkpoint.strip():
        _fail("image graph needs a non-empty checkpoint name")
    if isinstance(seed, bool) or not isinstance(seed, int):
        _fail(f"seed must be an integer, got {seed!r}")
    return {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": checkpoint},
        },
        "2": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["1", 1], "text": prompt},
        },
        "3": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["1", 1], "text": negative_prompt},
        },
        "4": {
            "class_type": "EmptyLatentImage",
            "inputs": {
                "batch_size": 1,
                "height": snap_to_grid(height),
                "width": snap_to_grid(width),
            },
        },
        "5": {
            "class_type": "KSampler",
            "inputs": {
                "cfg": 8.0,
                "denoise": 1.0,
                "latent_image": ["4", 0],
                "model": ["1", 0],
                "negative": ["3", 0],
                "positive": ["2", 0],
                "sampler_name": "euler",
                "scheduler": "normal",
                "seed": seed,
                "steps": 20,
            },
        },
        "6": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["5", 0], "vae": ["1", 2]},
        },
        "7": {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": "canvas", "images": ["6", 0]},
        },
    }


def _node_params(node: dict[str, Any]) -> dict[str, Any]:
    params = node.get("params", {})
    if not isinstance(params, dict):
        _fail(f"node {node['node_id']!r} params must be an object")
    return params


def _runtime_values(node: dict[str, Any], *, seed_override: int | None) -> dict[str, Any]:
    params = _node_params(node)
    prompt = params.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        _fail(f"video node {node['node_id']!r} needs a non-empty params.prompt")
    seed = seed_override if seed_override is not None else params.get("seed", 0)
    if isinstance(seed, bool) or not isinstance(seed, int):
        _fail(f"video node {node['node_id']!r} seed must be an integer")
    frames = params.get("frames", params.get("frame_count"))
    if frames is not None and (
        isinstance(frames, bool) or not isinstance(frames, int) or frames <= 0
    ):
        _fail(f"video node {node['node_id']!r} frames must be a positive integer")
    values: dict[str, Any] = {
        "prompt": prompt,
        "seed": seed,
        "negative_prompt": params.get("negative_prompt", ""),
        "ref_image": params.get("reference_image"),
    }
    if params.get("checkpoint") is not None:
        values["checkpoint"] = params["checkpoint"]
    if frames is not None:
        values["frames"] = frames
    for key in ("width", "height"):
        if params.get(key) is not None:
            values[key] = snap_to_grid(params[key])
    return values


def _validate_template(template: Any, *, node_id: str) -> dict[str, Any]:
    if not isinstance(template, dict):
        _fail(f"template for node {node_id!r} must be an object")
    nodes = template.get("nodes")
    if not isinstance(nodes, dict) or not nodes:
        _fail(f"template for node {node_id!r} needs a non-empty nodes object")
    for node_key, raw in nodes.items():
        if not isinstance(raw, dict):
            _fail(f"template node {node_key!r} must be an object")
        if not isinstance(raw.get("class_type"), str) or not raw["class_type"]:
            _fail(f"template node {node_key!r} needs a class_type string")
        if not isinstance(raw.get("inputs"), dict):
            _fail(f"template node {node_key!r} needs an inputs object")
    inject = template.get("inject", [])
    if not isinstance(inject, list):
        _fail(f"template for node {node_id!r} inject must be a list")
    for entry in inject:
        if not isinstance(entry, dict):
            _fail(f"template inject entries for node {node_id!r} must be objects")
        source = entry.get("source")
        if source not in _INJECT_SOURCES:
            _fail(
                f"template inject source {source!r} for node {node_id!r} "
                f"is unknown; allowed: {sorted(_INJECT_SOURCES)}"
            )
        target = str(entry.get("node", ""))
        field = entry.get("field")
        if target not in nodes:
            _fail(f"template inject names unknown node {target!r} for {node_id!r}")
        if not isinstance(field, str) or not field:
            _fail(f"template inject for node {node_id!r} needs a field name")
        if field not in nodes[target]["inputs"]:
            _fail(
                f"template inject target {target!r} field {field!r} does "
                f"not exist for node {node_id!r}; injection never creates fields"
            )
    return template


def translate_video_node(
    node: dict[str, Any],
    templates: Any,
    *,
    seed_override: int | None = None,
) -> dict[str, Any]:
    """Translate one ``video`` node into a ComfyUI API graph.

    ``templates`` maps a template name to either a template object
    (``{"nodes": {...}, "inject": [...]}``) or the string
    ``"builtin_image"``. The node selects its template with
    ``params["template"]``. Runtime values come only from the node
    params listed in :func:`_runtime_values`; sizes are snapped to
    the 32 grid. The input node and template are never mutated.
    """
    if not isinstance(node, dict) or not isinstance(node.get("node_id"), str):
        _fail("canvas node must be an object with a node_id string")
    if node.get("type") != "video":
        _fail(
            f"node {node['node_id']!r} has type {node.get('type')!r}; "
            "only video nodes translate to ComfyUI graphs"
        )
    if not isinstance(templates, dict):
        _fail("templates must be an object mapping template names to templates")
    params = _node_params(node)
    template_name = params.get("template")
    if not isinstance(template_name, str) or not template_name:
        _fail(
            f"video node {node['node_id']!r} needs params.template naming "
            "its ComfyUI template"
        )
    if template_name not in templates:
        _fail(
            f"video node {node['node_id']!r} names unknown template "
            f"{template_name!r}"
        )
    values = _runtime_values(node, seed_override=seed_override)
    chosen = templates[template_name]
    if chosen == "builtin_image":
        checkpoint = values.get("checkpoint")
        if checkpoint is None:
            _fail(
                f"video node {node['node_id']!r} using builtin_image needs "
                "params.checkpoint"
            )
        return build_image_graph(
            prompt=values["prompt"],
            seed=values["seed"],
            width=params.get("width", 512),
            height=params.get("height", 512),
            checkpoint=str(checkpoint),
            negative_prompt=str(values["negative_prompt"]),
        )
    template = _validate_template(chosen, node_id=node["node_id"])
    graph = copy.deepcopy(template["nodes"])
    for entry in template.get("inject", []):
        source = entry["source"]
        if source in ("width", "height") and source not in values:
            continue  # template keeps its own size when the node sets none
        if source == "checkpoint" and source not in values:
            continue  # template keeps its own checkpoint when unset
        if source == "frames" and source not in values:
            continue
        if source == "ref_image" and values.get("ref_image") is None:
            continue
        graph[str(entry["node"])]["inputs"][entry["field"]] = values[source]
    return graph


# ---------------------------------------------------------------- HTTP layer
# Standard library only, mirroring fasth3_local's error discipline:
# HTTP errors carry status plus body; unreachable servers are named.

def _post_json(
    base_url: str, path: str, payload: dict[str, Any], *, timeout: float
) -> Any:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        base_url.rstrip("/") + path,
        data=data,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:2000]
        raise CapabilityError(
            f"canvas_comfy_executor: ComfyUI HTTP {exc.code} on {path}: {body}"
        ) from exc
    except urllib.error.URLError as exc:
        raise CapabilityError(
            f"canvas_comfy_executor: cannot reach ComfyUI at {base_url} "
            f"({path}): {exc.reason}"
        ) from exc


def _get_history(
    base_url: str, prompt_id: str, *, timeout: float
) -> tuple[int | None, Any]:
    req = urllib.request.Request(base_url.rstrip("/") + "/history/" + prompt_id)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        exc.read()
        return exc.code, None
    except urllib.error.URLError as exc:
        raise CapabilityError(
            f"canvas_comfy_executor: cannot reach ComfyUI at {base_url} "
            f"(/history/{prompt_id}): {exc.reason}"
        ) from exc


def interrupt(base_url: str, *, timeout: float = 30.0) -> dict[str, Any]:
    """Post ``/interrupt`` (after a gateway-contract check) and report it.

    The gateway contract warns that interrupt is machine-wide: it
    cancels whatever is running, regardless of visitor. Callers
    must mean it.
    """
    report = check_gateway_request({"method": "POST", "path": "/interrupt"})
    if report["verdict"] != "pass":
        _fail(f"interrupt refused by the gateway contract: {report['failures']}")
    _post_json(base_url, "/interrupt", {}, timeout=timeout)
    return {"interrupted": True, "action": "POST /interrupt"}


def submit_and_poll(
    base_url: str,
    graph: dict[str, Any],
    *,
    visitor_id: str = DEFAULT_VISITOR_ID,
    poll_interval_s: float = DEFAULT_POLL_INTERVAL_S,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    sleep: Callable[[float], None] | None = None,
) -> dict[str, Any]:
    """Submit one API graph and poll ``/history`` until it completes.

    Returns ``{"prompt_id", "outputs", "elapsed_s"}``. A ComfyUI
    execution error raises :class:`CapabilityError` carrying the
    raw history text verbatim. On timeout, ``/interrupt`` is
    posted best-effort before the timeout error is raised.
    """
    if not isinstance(graph, dict) or not graph:
        _fail("ComfyUI graph must be a non-empty object")
    payload = {"prompt": graph, "client_id": visitor_id}
    body = json.dumps(payload).encode()
    report = check_gateway_request(
        {
            "method": "POST",
            "path": "/prompt",
            "body_bytes": len(body),
            "visitor_id": visitor_id,
        }
    )
    if report["verdict"] != "pass":
        _fail(f"POST /prompt refused by the gateway contract: {report['failures']}")
    resp = _post_json(base_url, "/prompt", payload, timeout=60.0)
    if not isinstance(resp, dict) or not resp.get("prompt_id"):
        _fail(f"ComfyUI /prompt returned no prompt_id: {resp}")
    prompt_id = str(resp["prompt_id"])
    history_report = check_gateway_request(
        {
            "method": "GET",
            "path": f"/history/{prompt_id}",
            "visitor_id": visitor_id,
            "resource_visitor_id": visitor_id,
        }
    )
    if history_report["verdict"] != "pass":
        _fail(
            f"GET /history refused by the gateway contract: "
            f"{history_report['failures']}"
        )
    do_sleep = sleep if sleep is not None else time.sleep
    t0 = time.time()
    while True:
        status, hist = _get_history(base_url, prompt_id, timeout=60.0)
        if status == 200 and isinstance(hist, dict) and prompt_id in hist:
            entry = hist[prompt_id]
            entry_status = entry.get("status", {}) if isinstance(entry, dict) else {}
            if entry_status.get("completed"):
                return {
                    "prompt_id": prompt_id,
                    "outputs": entry.get("outputs", {}),
                    "elapsed_s": round(time.time() - t0, 3),
                }
            if entry_status.get("status_str") == "error":
                raise CapabilityError(
                    "canvas_comfy_executor: ComfyUI execution error "
                    "(raw history): " + json.dumps(entry, indent=2)[:4000]
                )
            messages = entry_status.get("messages", [])
            if any(
                isinstance(m, list) and m and m[0] == "execution_error"
                for m in messages
            ):
                raise CapabilityError(
                    "canvas_comfy_executor: ComfyUI execution error "
                    "(raw history): " + json.dumps(entry, indent=2)[:4000]
                )
        # 404 (or an entry not yet present) means still queued: keep polling.
        if time.time() - t0 > timeout_s:
            try:
                interrupt(base_url)
            except CapabilityError:
                pass
            raise CapabilityError(
                f"canvas_comfy_executor: timed out after {timeout_s}s "
                f"waiting for prompt {prompt_id}; /interrupt was attempted"
            )
        do_sleep(poll_interval_s)


def _first_output_filename(outputs: Any) -> str | None:
    if not isinstance(outputs, dict):
        return None
    for node_output in outputs.values():
        if not isinstance(node_output, dict):
            continue
        for key in ("images", "videos", "gifs"):
            items = node_output.get(key)
            if isinstance(items, list) and items:
                first = items[0]
                if isinstance(first, dict) and isinstance(first.get("filename"), str):
                    return first["filename"]
    return None


def execute_canvas_workflow(
    workflow: Any,
    templates: Any,
    *,
    base_url: str,
    model: Any,
    snapshot: Any,
    visitor_id: str = DEFAULT_VISITOR_ID,
    max_parallel: int = 2,
    seed_batches: Any = None,
    poll_interval_s: float = DEFAULT_POLL_INTERVAL_S,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    sleep: Callable[[float], None] | None = None,
) -> dict[str, Any]:
    """Execute the ``video`` nodes of a canvas DAG through ComfyUI.

    The workflow is validated by ``canvas_workflow``; the plan
    comes from ``canvas_execution_schedule``; the model record is
    judged by ``model_install_gate`` against the caller-supplied
    snapshot before anything is submitted. The input workflow is
    never mutated: the returned ``workflow`` is the updated copy
    with run results applied. Per-node dispositions are reported
    under ``nodes``; ``submitted`` lists every prompt id accepted
    by the server.
    Composes (3O SPEC 1.2): check_model_install.
    """
    if not isinstance(base_url, str) or not base_url.strip():
        _fail("canvas_comfy_executor needs a non-empty base_url")
    validated = create_workflow(
        workflow["nodes"] if isinstance(workflow, dict) else workflow
    )
    plan = plan_canvas_execution(
        validated, max_parallel=max_parallel, seed_batches=seed_batches
    )
    if plan["verdict"] != "pass":
        return {
            "verdict": "fail",
            "plan": plan,
            "nodes": {},
            "submitted": [],
            "workflow": validated,
            "failures": plan["failures"],
        }
    gate = check_model_install(model, snapshot)
    if gate["verdict"] != "pass":
        return {
            "verdict": "fail",
            "plan": plan,
            "nodes": {},
            "submitted": [],
            "workflow": validated,
            "failures": gate["failures"],
            "model_gate": gate,
        }
    by_id = {node["node_id"]: node for node in validated["nodes"]}
    seed_tasks: dict[str, list[int]] = {}
    for task in plan.get("seed_tasks", []):
        seed_tasks.setdefault(task["node_id"], []).append(task["seed"])
    failed: set[str] = set()
    dispositions: dict[str, dict[str, Any]] = {}
    submitted: list[str] = []
    updated = validated

    def _upstream_failed(node_id: str, seen: frozenset[str]) -> bool:
        for upstream in by_id[node_id].get("inputs", []):
            if upstream in failed or _upstream_failed(upstream, seen | {node_id}):
                return True
        return False

    for batch in plan["batches"]:
        for node_id in batch["node_ids"]:
            node = by_id[node_id]
            if _upstream_failed(node_id, frozenset()):
                dispositions[node_id] = {
                    "status": "skipped",
                    "reason": "upstream_failed",
                }
                continue
            if node["type"] != "video":
                dispositions[node_id] = {
                    "status": "skipped",
                    "reason": "not_a_video_node",
                }
                continue
            seeds = seed_tasks.get(node_id)
            attempts = seeds if seeds else [None]
            node_ok = True
            last_error: str | None = None
            for seed in attempts:
                try:
                    graph = translate_video_node(
                        node, templates, seed_override=seed
                    )
                    result = submit_and_poll(
                        base_url,
                        graph,
                        visitor_id=visitor_id,
                        poll_interval_s=poll_interval_s,
                        timeout_s=timeout_s,
                        sleep=sleep,
                    )
                except CapabilityError as exc:
                    node_ok = False
                    last_error = str(exc)
                    break
                submitted.append(result["prompt_id"])
                artifact = _first_output_filename(result["outputs"])
                dispositions.setdefault(node_id, {
                    "status": "done",
                    "prompt_ids": [],
                    "outputs": [],
                })
                dispositions[node_id]["prompt_ids"].append(result["prompt_id"])
                dispositions[node_id]["outputs"].append(result["outputs"])
                if artifact is not None:
                    dispositions[node_id]["artifact"] = artifact
            if node_ok:
                artifact = dispositions[node_id].get("artifact")
                updated = apply_run_result(
                    updated, node_id, "done", artifact=artifact
                )
            else:
                failed.add(node_id)
                dispositions[node_id] = {
                    "status": "failed",
                    "error": last_error,
                }
                try:
                    updated = apply_run_result(updated, node_id, "failed")
                except CapabilityError:
                    pass
    verdict = "pass" if not failed else "fail"
    return {
        "verdict": verdict,
        "plan": plan,
        "nodes": dispositions,
        "submitted": submitted,
        "workflow": updated,
        "failures": (
            [
                {"node_id": node_id, "error": disp.get("error", "")}
                for node_id, disp in dispositions.items()
                if disp["status"] == "failed"
            ]
            if failed
            else []
        ),
        "model_gate": gate,
    }


_PARAMS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "nodes": {"type": "array"},
        "templates": {"type": "object"},
        "model": {"type": "object"},
        "snapshot": {"type": "object"},
        "base_url": {"type": "string"},
        "visitor_id": {"type": "string"},
        "max_parallel": {"type": "integer"},
        "seed_batches": {"type": "object"},
        "poll_interval_s": {"type": "number"},
        "timeout_s": {"type": "number"},
    },
    "required": ["nodes", "templates", "model", "base_url"],
    "additionalProperties": False,
}


def _render(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    result = execute_canvas_workflow(
        {"nodes": params["nodes"]},
        params["templates"],
        base_url=str(params["base_url"]),
        model=params["model"],
        snapshot=params.get("snapshot"),
        visitor_id=str(params.get("visitor_id", DEFAULT_VISITOR_ID)),
        max_parallel=int(params.get("max_parallel", 2)),
        seed_batches=params.get("seed_batches"),
        poll_interval_s=float(params.get("poll_interval_s", DEFAULT_POLL_INTERVAL_S)),
        timeout_s=float(params.get("timeout_s", DEFAULT_TIMEOUT_S)),
    )
    report_path = out_dir / "canvas_comfy_executor_report.json"
    report_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={
            "report_json": str(report_path),
            "verdict": result["verdict"],
            "submitted": result["submitted"],
            "failures": result["failures"],
        },
    )


def register_canvas_comfy_executor_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="pipeline.canvas_comfy_executor",
            kind="line",
            aspects=["16:9", "9:16", "1:1"],
            params_schema=_PARAMS_SCHEMA,
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Canvas to ComfyUI executor: translate canvas_workflow "
                "video nodes into ComfyUI API graphs (template plus "
                "runtime injection, sizes snapped to the 32 grid), "
                "submit after the gateway contract and model-install "
                "gate, poll /history at 800 ms with a 10-minute "
                "timeout, cancel via /interrupt. Tested only against "
                "a local fake ComfyUI server; no real ComfyUI "
                "generation has been run through it."
            ),
            line="pipeline",
        )
    )
    return ["pipeline.canvas_comfy_executor"]


register_canvas_comfy_executor_capabilities_once()
