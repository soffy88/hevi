"""Motion Canvas explainer gate (``qa.motion_canvas_explainer_gate``).

Clean-room restatement of the motion-canvas/motion-canvas
method (see ``ANIMATION_STUDIO_18_ATTRIBUTION.md``); no
upstream code appears here. Motion Canvas is the code-driven
animation-explainer layer: scenes on a timeline with audio
sync and word-level caption alignment, written in TypeScript
on Canvas. It complements hevi's Manim line (Python math
animation) and the Remotion line (React video rendering);
it does not replace either, so every plan must declare the
division of labour between the three explainer lines.
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

EXPLAINER_LINES = ("motion_canvas", "manim", "remotion")


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_motion_canvas_explainer(plan: Any) -> dict[str, Any]:
    """Validate a Motion Canvas-style explainer plan.

    Verdicts are ``pass`` / ``fail`` only. A plan fails when
    it is not an object, when the scene list is empty, when a
    scene lacks an id or a positive duration, when the scene
    durations do not sum to the declared total, when the
    audio-sync flag is not declared, when captions are enabled
    without word-level caption alignment, or when the division
    of labour between the motion_canvas / manim / remotion
    explainer lines is not declared.
    """
    issues: list[dict[str, Any]] = []

    def fail(code: str, detail: str) -> dict[str, Any]:
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [*issues, _issue(code, detail)],
            "executed_here": False,
        }

    if not isinstance(plan, dict):
        return fail("plan_not_object", "explainer plan must be a JSON object")
    for field in (
        "scenes",
        "total_seconds",
        "audio_sync",
        "division_of_labour",
    ):
        if field not in plan:
            return fail("plan_field_missing", f"explainer plan must carry {field!r}")
    scenes = plan["scenes"]
    if not isinstance(scenes, list) or not scenes:
        return fail("scenes_empty", "explainer plan needs at least one scene")
    total = 0.0
    for scene in scenes:
        if not isinstance(scene, dict):
            return fail("scene_not_object", "each scene must be an object")
        if not isinstance(scene.get("id"), str) or not scene["id"]:
            return fail("scene_id_missing", "each scene needs a non-empty id")
        duration = scene.get("duration_s")
        if not isinstance(duration, (int, float)) or duration <= 0:
            return fail(
                "scene_duration_not_positive",
                f"scene {scene.get('id')!r} needs a positive duration_s",
            )
        total += float(duration)
    declared = plan["total_seconds"]
    if not isinstance(declared, (int, float)) or declared <= 0:
        return fail(
            "total_seconds_not_positive",
            "total_seconds must be a positive number",
        )
    if abs(total - float(declared)) > 0.01:
        return fail(
            "scene_durations_do_not_sum",
            f"scene durations sum to {total}, declared total_seconds "
            f"is {declared}; the timeline must add up",
        )
    if not isinstance(plan["audio_sync"], bool):
        return fail(
            "audio_sync_not_declared",
            "audio_sync must be declared true or false",
        )
    if plan.get("captions") is True and plan.get("word_caption_alignment") is not True:
        return fail(
            "word_caption_alignment_missing",
            "captions are enabled but word-level caption alignment "
            "is not declared; audio and captions must align word by word",
        )
    division = plan["division_of_labour"]
    if not isinstance(division, str) or not division.strip():
        return fail(
            "division_of_labour_missing",
            "declare which explainer line owns what: motion_canvas, manim, or remotion",
        )
    if not any(line in division for line in EXPLAINER_LINES):
        return fail(
            "division_of_labour_unknown_line",
            "division_of_labour must name at least one explainer line: "
            "motion_canvas, manim, or remotion",
        )
    return {
        "verdict": "pass",
        "ok": True,
        "issues": [],
        "executed_here": False,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_motion_canvas_explainer(params.get("plan"))
    report_path = out_dir / "motion_canvas_explainer_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_motion_canvas_explainer_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.motion_canvas_explainer_gate",
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
                "Motion Canvas explainer gate: code-driven animation "
                "explanation with scenes summing to the declared total, "
                "audio sync, word-level caption alignment, and a declared "
                "division of labour between motion_canvas, manim, and remotion."
            ),
        )
    )
    return ["qa.motion_canvas_explainer_gate"]


__all__ = [
    "EXPLAINER_LINES",
    "check_motion_canvas_explainer",
    "register_motion_canvas_explainer_gate_capabilities_once",
]
