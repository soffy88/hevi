"""Deterministic reset and overlap audit gate (``qa.deterministic_reset_gate``).

Clean-room restatement of the method in ``hevi-vs-explainer-skills-9.md``
section 2 item 8 (BusyBee): an animation must replay cleanly, and text
must never collide. In hevi's caliber:

1. Deterministic reset: every scene declares the reset state its
   motion returns to -- the full list of touched properties restored
   to their initial values, including any looping motion. A scene
   with motion but no reset declaration fails; replay or seek must
   leave no dirty state behind.
2. Overlap audit: text pairs are swept at 0.5 second resolution. Any
   overlap found must carry a declared exemption reason; an overlap
   without one fails. The audit record names the sweep resolution so
   the check can be re-run.

This module judges plans only. It renders no frames and reads no
media bytes.
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

_SWEEP_RESOLUTION_S = 0.5


def _is_nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_deterministic_reset(plan: Any) -> dict[str, Any]:
    """Judge one reset/overlap plan. Returns a report; never raises.

    Verdicts are ``pass`` / ``fail`` only.
    """
    issues: list[dict[str, Any]] = []
    scenes_out: list[dict[str, Any]] = []
    if not isinstance(plan, dict):
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [_issue("plan_not_object", "plan must be a JSON object")],
            "scenes": [],
            "sweep_resolution_s": _SWEEP_RESOLUTION_S,
        }
    scenes = plan.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        issues.append(
            _issue("scenes_missing", "plan must declare a non-empty scenes list")
        )
        scenes = scenes if isinstance(scenes, list) else []
    for index, scene in enumerate(scenes):
        if not isinstance(scene, dict):
            issues.append(
                _issue("scene_not_object", f"scenes[{index}] must be an object")
            )
            continue
        scene_id = scene.get("id")
        if not _is_nonempty_str(scene_id):
            issues.append(
                _issue("scene_id_missing", f"scenes[{index}] must declare an id")
            )
        reset = scene.get("reset")
        if not isinstance(reset, dict):
            issues.append(
                _issue(
                    "reset_missing",
                    f"scene {scene_id!r} must declare a reset state",
                )
            )
        else:
            restored = reset.get("restored_properties")
            if not isinstance(restored, list) or not restored or not all(
                _is_nonempty_str(item) for item in restored
            ):
                issues.append(
                    _issue(
                        "reset_properties_missing",
                        f"scene {scene_id!r} must list the properties "
                        "its reset restores",
                    )
                )
            if reset.get("covers_loops") is not True and scene.get("has_loops"):
                issues.append(
                    _issue(
                        "reset_loops_uncovered",
                        f"scene {scene_id!r} has looping motion but its "
                        "reset does not declare covers_loops",
                    )
                )
        overlaps = scene.get("overlaps")
        if overlaps is not None:
            if not isinstance(overlaps, list):
                issues.append(
                    _issue(
                        "overlaps_not_list",
                        f"scene {scene_id!r} overlaps must be a list",
                    )
                )
            else:
                for overlap in overlaps:
                    if not isinstance(overlap, dict):
                        issues.append(
                            _issue(
                                "overlap_not_object",
                                f"scene {scene_id!r} overlap entries must be objects",
                            )
                        )
                        continue
                    if not _is_nonempty_str(overlap.get("exemption_reason")):
                        issues.append(
                            _issue(
                                "overlap_without_exemption",
                                f"scene {scene_id!r} overlap between "
                                f"{overlap.get('a')!r} and {overlap.get('b')!r} "
                                "carries no exemption reason",
                            )
                        )
        scenes_out.append({"id": scene_id})
    audit = plan.get("overlap_audit")
    if audit is not None:
        if audit.get("sweep_resolution_s") != _SWEEP_RESOLUTION_S:
            issues.append(
                _issue(
                    "sweep_resolution_mismatch",
                    "overlap audit must declare sweep_resolution_s of "
                    f"{_SWEEP_RESOLUTION_S}",
                )
            )
    verdict = "fail" if issues else "pass"
    return {
        "verdict": verdict,
        "ok": verdict == "pass",
        "issues": issues,
        "scenes": scenes_out,
        "sweep_resolution_s": _SWEEP_RESOLUTION_S,
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    report = check_deterministic_reset(params.get("plan"))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "deterministic_reset_gate_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={
            "report_json": str(report_path),
            "ok": report["ok"],
        },
    )


def register_deterministic_reset_gate_capabilities_once() -> list[str]:
    """Register ``qa.deterministic_reset_gate`` on the unified registry (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.deterministic_reset_gate",
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
            description=(
                "Deterministic reset and overlap audit gate: every scene "
                "declares the reset state replay returns to, and every "
                "text overlap found by the 0.5 second sweep carries an "
                "exemption reason. Plans are judged, never re-rendered."
            ),
            line="qa",
        )
    )
    return ["qa.deterministic_reset_gate"]


register_deterministic_reset_gate_capabilities_once()
