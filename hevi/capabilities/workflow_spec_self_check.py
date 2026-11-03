"""Workflow specification self-check (``qa.workflow_spec_self_check``).

Clean-room restatement of the workflow-spec self-check idea
described in the Infinite Creation review (see
``INFINITE_CREATION_ATTRIBUTION.md``): a workflow is registered
from a hand-written specification that maps semantic roles to
nodes, and the specification must be checked against the
workflow itself before anything is submitted. Every role must
point at a node that exists, node ids must be unique, and every
node whose class the checker recognises must have a role. The
role guessing here is a small deterministic rule set written for
this gate -- class-name patterns and parameter names only, no
model call, no copied mapping table.

This module judges specifications only. It never submits a
workflow, never contacts a backend, and never touches a budget.
A node class the checker does not recognise is ``not_checked``,
never a pass and never a failure: unknown machinery is reported
as unknown.
"""

from __future__ import annotations

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


def _issue(code: str, detail: str, **extra: Any) -> dict[str, Any]:
    issue = {"code": code, "detail": f"qa.workflow_spec_self_check: {detail}"}
    issue.update(extra)
    return issue


def guess_node_role(node: dict[str, Any]) -> str | None:
    """Guess one node's semantic role from its class and inputs.

    Deterministic rules only: class-name patterns first, then
    parameter names. Returns None when the class is not
    recognised, which the checker records as not_checked.
    """
    class_name = str(node.get("class", ""))
    inputs = node.get("inputs", {})
    if not isinstance(inputs, dict):
        inputs = {}
    lowered = class_name.lower()
    if "textencode" in lowered or "cliptext" in lowered:
        return "text_prompt"
    if "checkpoint" in lowered or "unetloader" in lowered or "model loader" in lowered:
        return "model_loader"
    if "sampler" in lowered or "scheduler" in lowered:
        return "sampler"
    if "vae" in lowered and "decode" in lowered:
        return "vae_decode"
    if "vae" in lowered and "encode" in lowered:
        return "vae_encode"
    if "saveimage" in lowered or "savevideo" in lowered or "saveanimation" in lowered:
        return "output"
    if "latent" in lowered and ("empty" in lowered or "from" in lowered):
        return "latent_shape"
    if "seed" in lowered:
        return "seed"
    if "lora" in lowered:
        return "lora"
    if "width" in inputs and "height" in inputs:
        return "dimensions"
    if "seconds" in inputs or "frame_count" in inputs or "frames" in inputs:
        return "duration"
    if "image" in inputs and "load" in lowered:
        return "image_input"
    if "audio" in inputs and "load" in lowered:
        return "audio_input"
    return None


def analyze_workflow(spec: dict[str, Any]) -> dict[str, Any]:
    """Return the deterministic role guess for every node in ``spec``."""
    nodes = spec.get("nodes", [])
    guessed: dict[str, str | None] = {}
    for node in nodes:
        if isinstance(node, dict) and node.get("id"):
            guessed[str(node["id"])] = guess_node_role(node)
    return {"roles": guessed, "node_count": len(guessed)}


def check_workflow_spec(spec: Any) -> dict[str, Any]:
    """Judge one workflow specification against its node list.

    ``spec`` carries ``nodes`` (each with ``id`` and ``class``)
    and ``roles`` (role name to node id). Verdict ``pass`` means
    ids are unique, every role points at an existing node, and
    every recognised node has a role. Unrecognised node classes
    are ``not_checked``.
    """
    if not isinstance(spec, dict):
        raise CapabilityError("workflow spec must be an object")
    issues: list[dict[str, Any]] = []
    not_checked: list[dict[str, Any]] = []
    nodes = spec.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        raise CapabilityError("workflow spec requires a non-empty nodes list")
    node_ids: dict[str, dict[str, Any]] = {}
    for index, node in enumerate(nodes):
        if not isinstance(node, dict):
            issues.append(_issue("node_not_object", f"node {index} is not an object"))
            continue
        node_id = node.get("id")
        if not node_id:
            issues.append(_issue("node_id_missing", f"node {index} lacks an id"))
            continue
        node_id = str(node_id)
        if node_id in node_ids:
            issues.append(_issue("node_id_duplicate", f"node id {node_id} is duplicated"))
        node_ids[node_id] = node
        if not node.get("class"):
            issues.append(_issue("node_class_missing", f"node {node_id} lacks a class"))
    roles = spec.get("roles")
    if not isinstance(roles, dict):
        raise CapabilityError("workflow spec requires a roles object")
    covered: set[str] = set()
    for role, node_id in roles.items():
        if str(node_id) not in node_ids:
            issues.append(
                _issue("role_dangling", f"role {role} points at missing node {node_id}", role=role)
            )
        else:
            covered.add(str(node_id))
    for node_id, node in node_ids.items():
        guessed = guess_node_role(node)
        if guessed is None:
            not_checked.append(
                {
                    "code": "node_class_unrecognised",
                    "detail": f"node {node_id} class {node.get('class')} is not recognised",
                    "node": node_id,
                }
            )
        elif node_id not in covered:
            issues.append(
                _issue(
                    "recognised_node_unroled",
                    f"node {node_id} (guessed role {guessed}) has no role in the spec",
                    node=node_id,
                    guessed_role=guessed,
                )
            )
    if issues:
        verdict = "fail"
    elif not_checked:
        verdict = "not_checked"
    else:
        verdict = "pass"
    return {
        "ok": verdict != "fail",
        "verdict": verdict,
        "issues": issues,
        "not_checked": not_checked,
        "node_count": len(node_ids),
        "role_count": len(roles),
        "guessed_roles": {nid: guess_node_role(node) for nid, node in node_ids.items()},
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_workflow_spec(params.get("spec"))
    report_path = out_dir / "workflow_spec_self_check.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_workflow_spec_self_check_capabilities_once() -> list[str]:
    """Register ``qa.workflow_spec_self_check`` on the unified registry (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.workflow_spec_self_check",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "spec": {"type": "object"},
                },
                "required": ["spec"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Workflow spec self-check: role mappings must point at "
                "existing nodes, node ids must be unique, and every "
                "recognised node must have a role; unrecognised classes are "
                "not_checked, never passes."
            ),
        )
    )
    return ["qa.workflow_spec_self_check"]


__all__ = [
    "analyze_workflow",
    "check_workflow_spec",
    "guess_node_role",
    "register_workflow_spec_self_check_capabilities_once",
]
