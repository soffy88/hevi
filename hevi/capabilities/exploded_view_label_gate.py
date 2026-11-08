"""Exploded-view label gate (``qa.exploded_view_label_gate``).

Discipline gate only. An exploded-view plan (an object drawn
with its layers lifted apart, each layer labelled) must
declare between one and six layers in top-to-bottom order,
each layer with a short name, a short note, an anchor point,
and a leader line to its label. Only flat, layered objects
qualify; any other object claiming an exploded view fails.
Layer order must run 1..n without gaps, names stay short,
and notes stay short, so labels stay readable in a vertical
frame. Hevi's existing reference-decompose work analyses
already-made videos; this gate judges a new exploded-view
plan. It renders nothing. See ANIMATION_SKILLS_ATTRIBUTION.md.
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

MAX_LAYERS = 6
MAX_NAME_CHARS = 16
MAX_NOTE_CHARS = 22


def _issue(code: str, detail: str) -> dict[str, str]:
    return {"code": code, "detail": detail}


def check_exploded_view_labels(plan: Any) -> dict[str, Any]:
    """Check an exploded-view plan for layer/label discipline.

    Returns a report dict with ``verdict`` pass/fail, ``ok``,
    and ``issues``. Too many layers, broken order, missing
    anchors or leader lines, over-long text, and non-layered
    objects all fail.
    """
    issues: list[dict[str, str]] = []
    if not isinstance(plan, dict):
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [_issue("plan_not_object", "plan must be a JSON object")],
        }
    if plan.get("flat_layered_object") is not True:
        issues.append(
            _issue(
                "object_not_flat_layered",
                "only flat, layered objects qualify for an "
                "exploded view",
            )
        )
    layers = plan.get("layers")
    if not isinstance(layers, list) or not layers:
        issues.append(
            _issue("layers_missing", "plan must declare a non-empty layers list")
        )
        layers = layers if isinstance(layers, list) else []
    if len(layers) > MAX_LAYERS:
        issues.append(
            _issue(
                "too_many_layers",
                f"at most {MAX_LAYERS} layers may be labelled",
            )
        )
    for index, layer in enumerate(layers):
        label = f"layers[{index}]"
        if not isinstance(layer, dict):
            issues.append(
                _issue(f"{label}:not_object", "each layer must be an object")
            )
            continue
        order = layer.get("order")
        if order != index + 1:
            issues.append(
                _issue(
                    f"{label}:order_wrong",
                    "layer order must run 1..n top to bottom",
                )
            )
        name = layer.get("name")
        if not isinstance(name, str) or not name.strip():
            issues.append(
                _issue(f"{label}:name_missing", "each layer must name itself")
            )
        elif len(name) > MAX_NAME_CHARS:
            issues.append(
                _issue(
                    f"{label}:name_too_long",
                    f"layer names stay within {MAX_NAME_CHARS} characters",
                )
            )
        note = layer.get("note")
        if not isinstance(note, str) or not note.strip():
            issues.append(
                _issue(f"{label}:note_missing", "each layer must carry a note")
            )
        elif len(note) > MAX_NOTE_CHARS:
            issues.append(
                _issue(
                    f"{label}:note_too_long",
                    f"layer notes stay within {MAX_NOTE_CHARS} characters",
                )
            )
        anchor = layer.get("anchor")
        if not isinstance(anchor, dict) or "x" not in anchor or "y" not in anchor:
            issues.append(
                _issue(
                    f"{label}:anchor_missing",
                    "each layer must declare an anchor point",
                )
            )
        if layer.get("leader_line") is not True:
            issues.append(
                _issue(
                    f"{label}:leader_line_missing",
                    "each layer must declare a leader line to "
                    "its label",
                )
            )
    return {
        "verdict": "fail" if issues else "pass",
        "ok": not issues,
        "issues": issues,
        "max_layers": MAX_LAYERS,
    }


def _render(params: dict[str, Any], out_dir: Any, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_exploded_view_labels(params.get("plan"))
    report_path = out_dir / "exploded_view_labels.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_exploded_view_label_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.exploded_view_label_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "plan": {"type": "object"},
                },
                "required": ["plan"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="oskill",
            description=(
                "Exploded-view label gate: one to six layers in "
                "top-to-bottom order, each with a short name, a "
                "short note, an anchor, and a leader line; only "
                "flat, layered objects qualify."
            ),
        )
    )
    return ["qa.exploded_view_label_gate"]


__all__ = [
    "check_exploded_view_labels",
    "register_exploded_view_label_gate_capabilities_once",
]
