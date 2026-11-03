"""Manim scene plan gate (``qa.manim_scene_plan_gate``).

Clean-room restatement of the composer planning layer in
``hevi-vs-explainer-skills-9.md`` section 2 item 6 (Manim Skill):
plan before code. hevi already has a Manim execution layer
(``video.manim_render``, Manim Community Edition, real LaTeX); this
gate is the missing planning layer that must run before any scene is
written. It judges plan text only and never renders:

1. The engine must be declared first -- ``manimce`` or ``manimgl``.
   The two frameworks' imports and APIs are incompatible and code
   must never be mixed; a plan with no engine declaration fails, and
   an import line from the other engine fails.
2. The plan must name the aha moment, the misconception it corrects,
   and the audience, before any scene is specified.
3. Every scene declares its goal, its duration, and the reason each
   step dwells as long as it does. A scene without a dwell reason
   fails.
4. Formula typesetting needs must be declared (LaTeX required or
   not); a plan that uses formulas without declaring the typesetting
   need fails.

No code is executed, no Manim is imported, and no video is produced
by this gate.
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

_ENGINES = ("manimce", "manimgl")
_ENGINE_IMPORT_MARKS = {
    "manimce": ("from manim import",),
    "manimgl": ("from manimlib import", "from manimlib.", "import manimlib"),
}


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_manim_scene_plan(plan: Any) -> dict[str, Any]:
    """Judge one Manim scene plan. Returns a report; never raises.

    Verdicts are ``pass`` / ``fail`` only.
    """
    issues: list[dict[str, Any]] = []
    scenes_out: list[dict[str, Any]] = []
    if not isinstance(plan, dict):
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [_issue("plan_not_object", "plan must be a JSON object")],
            "engine": None,
            "scenes": [],
        }
    engine = plan.get("engine")
    if engine not in _ENGINES:
        issues.append(
            _issue(
                "engine_missing",
                "plan must declare its engine first: 'manimce' or 'manimgl'",
            )
        )
        engine = None
    for field, code in (
        ("aha_moment", "aha_moment_missing"),
        ("misconception", "misconception_missing"),
        ("audience", "audience_missing"),
    ):
        if not _is_nonempty_str(plan.get(field)):
            issues.append(_issue(code, f"plan must declare {field} before any scene"))
    if not isinstance(plan.get("latex_required"), bool):
        issues.append(
            _issue(
                "latex_need_undeclared",
                "plan must declare latex_required as true or false",
            )
        )
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
        if not _is_nonempty_str(scene.get("goal")):
            issues.append(
                _issue("scene_goal_missing", f"scene {scene_id!r} must declare a goal")
            )
        duration = scene.get("duration_s")
        if not _is_number(duration) or duration <= 0:
            issues.append(
                _issue(
                    "scene_duration_missing",
                    f"scene {scene_id!r} must declare a positive duration_s",
                )
            )
        if not _is_nonempty_str(scene.get("dwell_reason")):
            issues.append(
                _issue(
                    "dwell_reason_missing",
                    f"scene {scene_id!r} must declare why each step "
                    "dwells as long as it does",
                )
            )
        if engine is not None:
            other = "manimgl" if engine == "manimce" else "manimce"
            imports = scene.get("imports")
            if isinstance(imports, list):
                for line in imports:
                    if isinstance(line, str) and any(
                        mark in line for mark in _ENGINE_IMPORT_MARKS[other]
                    ):
                        issues.append(
                            _issue(
                                "engine_import_mismatch",
                                f"scene {scene_id!r} declares engine {engine} "
                                f"but imports from the {other} framework",
                            )
                        )
        scenes_out.append({"id": scene_id})
    verdict = "fail" if issues else "pass"
    return {
        "verdict": verdict,
        "ok": verdict == "pass",
        "issues": issues,
        "engine": engine,
        "scenes": scenes_out,
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    report = check_manim_scene_plan(params.get("plan"))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "manim_scene_plan_gate_report.json"
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


def register_manim_scene_plan_gate_capabilities_once() -> list[str]:
    """Register ``qa.manim_scene_plan_gate`` on the unified registry (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.manim_scene_plan_gate",
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
                "Manim scene plan gate: engine declared first, aha moment "
                "and misconception named, every scene with goal, duration, "
                "and dwell reason, LaTeX need declared. Plan text only; "
                "no rendering is performed."
            ),
            line="qa",
        )
    )
    return ["qa.manim_scene_plan_gate"]


register_manim_scene_plan_gate_capabilities_once()
