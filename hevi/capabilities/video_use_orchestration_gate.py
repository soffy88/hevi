"""video-use orchestration increment gate (``qa.video_use_orchestration_gate``).

Clean-room restatement of the orchestration layer of
browser-use/video-use (see ``VIDEO_SKILLS_10_ATTRIBUTION.md``);
no upstream code appears in this gate.

This gate covers only the orchestration increments that hevi
does not already own. ``edit.video_use`` (2026-10-25) already
owns the twelve hard rules: subtitles last (R01), per-segment
extract plus lossless concat (R02), 30ms fades (R03), overlay
PTS shift (R04), output-timeline subtitles (R05), word-boundary
cuts and padding (R06/R07), verbatim word-level ASR and
transcript caching (R08/R09), parallel animation (R10),
strategy confirmation (R11), and session output location
(R12). This gate therefore checks only the four orchestration
increments: a session-memory file (``project.md``) that survives
across runs, an ordered colour-grade chain that runs before
subtitles, parallel overlay-layer generation (one declared
layer type per cut range), and a per-cut self-check manifest.
Any voiceover in the orchestration must name an authorized
voice with an authorization proof; ElevenLabs is never
accepted anywhere in the plan.
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

OVERLAY_LAYER_TYPES = ("hyperframes", "remotion", "manim", "pil")


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_video_use_orchestration(plan: Any) -> dict[str, Any]:
    """Validate a video-use orchestration plan.

    Verdicts are ``pass`` / ``fail`` only. A plan fails when
    it is not an object, when session memory, the colour-grade
    chain, the overlay layers, or the per-cut self-check is
    missing or malformed, when a grade step does not run before
    subtitles, when a layer type is outside the closed
    vocabulary or a layer is not ready, when a cut self-check
    verdict is ``fail`` or a cut id repeats, or when any voice
    lacks an authorization proof or the plan names ElevenLabs.
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
        return fail("plan_not_object", "orchestration plan must be a JSON object")
    if "elevenlabs" in json.dumps(plan, ensure_ascii=False).lower():
        return fail(
            "elevenlabs_not_accepted",
            "ElevenLabs is never accepted in a video-use orchestration plan; "
            "voiceover must use a hevi authorized voice",
        )
    for field in (
        "session_memory",
        "color_grade_chain",
        "overlay_layers",
        "per_cut_self_check",
    ):
        if field not in plan:
            return fail("plan_field_missing", f"orchestration plan must carry {field!r}")
    memory = plan["session_memory"]
    if not isinstance(memory, dict):
        return fail("session_memory_not_object", "session_memory must be an object")
    if not isinstance(memory.get("project_md"), str) or not memory["project_md"]:
        return fail(
            "session_memory_project_md_missing",
            "session_memory must name a project.md file that survives across runs",
        )
    if not isinstance(memory.get("last_cut_index"), int) or memory["last_cut_index"] < 0:
        return fail(
            "session_memory_last_cut_missing",
            "session_memory must carry a non-negative last_cut_index",
        )
    chain = plan["color_grade_chain"]
    if not isinstance(chain, list) or not chain:
        return fail(
            "color_grade_chain_empty",
            "color_grade_chain needs at least one grade step",
        )
    for order, step in enumerate(chain):
        if not isinstance(step, dict):
            return fail("grade_step_not_object", "each grade step must be an object")
        if not isinstance(step.get("name"), str) or not step["name"]:
            return fail("grade_step_name_missing", "each grade step needs a non-empty name")
        if step.get("order") != order:
            return fail(
                "grade_step_order_wrong",
                f"grade step {step.get('name')!r} must carry order {order}",
            )
        if step.get("applies_before_subtitles") is not True:
            return fail(
                "grade_step_after_subtitles",
                f"grade step {step.get('name')!r} must run before subtitles",
            )
    layers = plan["overlay_layers"]
    if not isinstance(layers, list) or not layers:
        return fail("overlay_layers_empty", "overlay_layers needs at least one layer")
    for layer in layers:
        if not isinstance(layer, dict):
            return fail("overlay_layer_not_object", "each overlay layer must be an object")
        if layer.get("type") not in OVERLAY_LAYER_TYPES:
            return fail(
                "overlay_layer_type_unknown",
                "overlay layer type must be one of: " + ", ".join(OVERLAY_LAYER_TYPES),
            )
        cut_range = layer.get("cut_range")
        if (
            not isinstance(cut_range, (list, tuple))
            or len(cut_range) != 2
            or not all(isinstance(v, int) and v >= 0 for v in cut_range)
            or cut_range[0] >= cut_range[1]
        ):
            return fail(
                "overlay_layer_cut_range_bad",
                "each overlay layer needs a cut_range [start, end] with 0 <= start < end",
            )
        if layer.get("ready") is not True:
            return fail(
                "overlay_layer_not_ready",
                f"overlay layer {layer.get('type')!r} must be declared ready",
            )
    checks = plan["per_cut_self_check"]
    if not isinstance(checks, list) or not checks:
        return fail(
            "per_cut_self_check_empty",
            "per_cut_self_check needs at least one cut verdict",
        )
    seen: set[str] = set()
    for check in checks:
        if not isinstance(check, dict):
            return fail("cut_check_not_object", "each cut self-check must be an object")
        cut_id = check.get("cut_id")
        if not isinstance(cut_id, str) or not cut_id:
            return fail("cut_check_id_missing", "each cut self-check needs a cut_id")
        if cut_id in seen:
            return fail("cut_check_id_duplicate", f"cut_id {cut_id!r} is checked twice")
        seen.add(cut_id)
        if check.get("verdict") not in ("pass", "fail"):
            return fail(
                "cut_check_verdict_unknown",
                f"cut {cut_id!r} verdict must be pass or fail",
            )
        if not isinstance(check.get("note"), str) or not check["note"]:
            return fail("cut_check_note_missing", f"cut {cut_id!r} needs a note")
        if check["verdict"] == "fail":
            return fail(
                "cut_self_check_failed",
                f"cut {cut_id!r} failed its self-check: {check['note']}",
            )
    voice = plan.get("voice")
    if voice is not None:
        if not isinstance(voice, dict):
            return fail("voice_not_object", "voice must be an object")
        if not isinstance(voice.get("voice_id"), str) or not voice["voice_id"]:
            return fail("voice_id_missing", "voice must name a voice_id")
        if (
            not isinstance(voice.get("authorization_proof"), str)
            or not voice["authorization_proof"]
        ):
            return fail(
                "voice_authorization_missing",
                "voice must carry an authorization proof; unproven voices fail",
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
    report = check_video_use_orchestration(params.get("plan"))
    report_path = out_dir / "video_use_orchestration_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_video_use_orchestration_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.video_use_orchestration_gate",
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
                "video-use orchestration increment gate: session memory, "
                "an ordered colour-grade chain before subtitles, parallel "
                "overlay-layer generation, and a per-cut self-check manifest; "
                "ElevenLabs is never accepted, voiceover needs an authorized "
                "voice with proof. Increments only: the twelve hard rules "
                "stay with edit.video_use."
            ),
        )
    )
    return ["qa.video_use_orchestration_gate"]


__all__ = [
    "OVERLAY_LAYER_TYPES",
    "check_video_use_orchestration",
    "register_video_use_orchestration_gate_capabilities_once",
]
