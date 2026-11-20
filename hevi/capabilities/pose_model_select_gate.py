"""Model selection gate (``qa.pose_model_select_gate``).

Generation-protocol selection for the pose gallery workbench:
five protocols (Gemini, GPT Image, Qwen, Doubao, local
ComfyUI), verified from the upstream ``aiGenerator.ts``
implementation. Keys are always user-supplied; hevi never
stores a key, so a selection that names hevi as the key
owner fails.

Model-list drift, stated plainly: the upstream code already
lists gpt-image-2.6-sunburst/flare while the README still
stops at 2.5. A model claimed from the README alone fails
as stale; the model source must be ``code``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

PROTOCOLS: frozenset[str] = frozenset({"gemini", "gpt-image", "qwen", "doubao", "comfyui"})
TASKS: frozenset[str] = frozenset({"daily", "quality", "edit", "local"})


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_pose_model_selection(selection: Any) -> dict[str, Any]:
    """Validate one generation-protocol selection.

    Verdicts are ``pass`` / ``fail`` only. A selection fails
    when the protocol or task is unknown, the model is missing
    or sourced from the stale README, the key owner is not the
    user, or a local ComfyUI selection does not declare a local
    ComfyUI instance.
    """
    issues: list[dict[str, Any]] = []

    def fail(code: str, detail: str) -> dict[str, Any]:
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [*issues, _issue(code, detail)],
            "executed_here": False,
        }

    if not isinstance(selection, dict):
        return fail("selection_not_object", "model selection must be a JSON object")
    protocol = selection.get("protocol")
    if protocol not in PROTOCOLS:
        return fail(
            "unknown_protocol",
            f"protocol must be one of {sorted(PROTOCOLS)}, got {protocol!r}",
        )
    model = selection.get("model")
    if not isinstance(model, str) or not model.strip():
        return fail("model_missing", "model selection must name a model")
    if selection.get("model_source") == "readme":
        return fail(
            "stale_readme_model",
            "the README model list is stale (it stops at "
            "gpt-image 2.5 while the code already lists 2.6); the "
            "model source must be code, not readme",
        )
    if selection.get("task") not in TASKS:
        return fail(
            "unknown_task",
            f"task must be one of {sorted(TASKS)} (daily, quality, "
            f"edit, local), got {selection.get('task')!r}",
        )
    if selection.get("key_owner") != "user":
        return fail(
            "key_owner_not_user",
            "generation keys are always user-supplied; hevi never "
            "stores a key, so key_owner must be user",
        )
    if protocol == "comfyui" and selection.get("local_comfyui") is not True:
        return fail(
            "local_comfyui_missing",
            "a local ComfyUI selection must declare a local ComfyUI instance (local_comfyui true)",
        )
    return {
        "verdict": "pass",
        "ok": True,
        "issues": [],
        "protocol": protocol,
        "model": model,
        "task": selection.get("task"),
        "executed_here": False,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_pose_model_selection(params.get("selection"))
    report_path = out_dir / "pose_model_select_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_pose_model_select_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.pose_model_select_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "selection": {"type": "object"},
                },
                "required": ["selection"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="oskill",
            description=(
                "Pose-gallery model selection gate: five protocols "
                "verified from code, keys always user-supplied, "
                "README-sourced models refused as stale, local "
                "ComfyUI declared explicitly."
            ),
        )
    )
    return ["qa.pose_model_select_gate"]


__all__ = [
    "PROTOCOLS",
    "TASKS",
    "check_pose_model_selection",
    "register_pose_model_select_gate_capabilities_once",
]
