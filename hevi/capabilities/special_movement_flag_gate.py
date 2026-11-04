"""Special movement flag gate (``qa.special_movement_flag_gate``).

Clean-room discipline gate only. Three movements in the catalogue
are composite or time-class effects, not single physical moves, and
a plan that uses one must declare how it is built:

* ``earth_zoom_out`` and ``infinite_zoom``: ``composite_segments``,
  a non-empty list naming the segments the effect is composited
  from;
* ``time_lapse``: ``compression_ratio``, the time compression the
  shot declares (for example ``"60x"``).

Using one of the three with no such declaration fails; ordinary
movements need no flag and pass. This gate judges the plan only
and renders nothing. No site prompt text is copied here. See
CAMERA_MOVEMENTS_ATTRIBUTION.md.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hevi.capabilities.camera_movement_index import SPECIAL_FLAGS
from hevi.capabilities.cinematic_techniques import load_movements
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_special_movement_flags(plan: Any) -> dict[str, Any]:
    """Validate a one-movement plan's special flags. Returns a report.

    A plan is ``{"movement_id": ..., "composite_segments": [...],
    "compression_ratio": ...}``. Unknown movement ids fail.
    """
    issues: list[dict[str, Any]] = []
    movement_id: Any = None
    flag_kind: Any = None
    if not isinstance(plan, dict):
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [
                _issue("plan_not_object", "special-flag plan must be an object")
            ],
            "movement_id": None,
            "special_flag": None,
        }
    movement_id = plan.get("movement_id")
    if not isinstance(movement_id, str) or not movement_id:
        issues.append(
            _issue("movement_id_missing", "plan names no movement")
        )
    elif movement_id not in {r["id"] for r in load_movements()}:
        issues.append(
            _issue(
                f"unknown_movement_id:{movement_id}",
                f"{movement_id!r} is not in the movement vocabulary",
            )
        )
    else:
        flag_kind = SPECIAL_FLAGS.get(movement_id)
        if flag_kind == "composite_segments":
            segments = plan.get("composite_segments")
            if not isinstance(segments, list) or not segments:
                issues.append(
                    _issue(
                        "special_flag_missing:composite_segments",
                        f"{movement_id!r} is a composite effect and must "
                        "declare a non-empty composite_segments list",
                    )
                )
            elif not all(isinstance(s, str) and s.strip() for s in segments):
                issues.append(
                    _issue(
                        "composite_segments_not_text",
                        "every composite segment must be a non-empty string",
                    )
                )
        elif flag_kind == "time_compression":
            ratio = plan.get("compression_ratio")
            if ratio is None or (isinstance(ratio, str) and not ratio.strip()):
                issues.append(
                    _issue(
                        "special_flag_missing:time_compression",
                        f"{movement_id!r} compresses time and must declare "
                        "a compression_ratio",
                    )
                )
    return {
        "verdict": "fail" if issues else "pass",
        "ok": not issues,
        "issues": issues,
        "movement_id": movement_id,
        "special_flag": flag_kind,
    }


def _render(params: dict[str, Any], out_dir: Any, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_special_movement_flags(params.get("plan"))
    report_path = out_dir / "special_movement_flag.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_special_movement_flag_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.special_movement_flag_gate",
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
                "Special movement flag gate: earth zoom out and "
                "infinite zoom must declare composite_segments and "
                "time-lapse must declare a compression_ratio; using "
                "one without its declaration fails."
            ),
        )
    )
    return ["qa.special_movement_flag_gate"]


__all__ = [
    "check_special_movement_flags",
    "register_special_movement_flag_gate_capabilities_once",
]
