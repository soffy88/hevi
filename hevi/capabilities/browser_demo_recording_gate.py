"""Browser demo recording gate (``qa.browser_demo_recording_gate``).

Clean-room restatement of the screenshot-to-MP4 browser demo
method of MengTo/Skills ``browser-video-recording`` (see
``VIDEO_SKILLS_10_ATTRIBUTION.md``); no upstream code appears
in this gate.

hevi owns only browser checks (``qa.browser_check_executor``,
``qa.browser_check_matrix``); it has no browser demo recording
capability. This gate owns the whole method: a declared
screenshot source from hevi's own browser automation (never
bound to the Codex in-app browser), frame parameters, a
choreographed interaction list (mouse moves, clicks, follow
zooms, scrolls), and a Pillow plus ffmpeg render with an
ffprobe truth check.
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

INTERACTION_TYPES = ("mouse_move", "click", "zoom_follow", "scroll")
ASPECTS = ("4:3", "16:9", "9:16")
MAX_DIMENSION = 3840


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_browser_demo_recording(plan: Any) -> dict[str, Any]:
    """Validate a browser demo recording plan.

    Verdicts are ``pass`` / ``fail`` only. A plan fails when
    it is not an object, when the screenshot source is missing
    or bound to the Codex in-app browser, when frame parameters
    are missing or out of range, when the interaction list is
    empty or malformed, when the render tool or the ffprobe
    check is not declared, or when the duration is not
    positive.
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
        return fail("plan_not_object", "demo recording plan must be a JSON object")
    for field in ("capture_source", "frames", "interactions", "render", "duration_s"):
        if field not in plan:
            return fail("plan_field_missing", f"demo recording plan must carry {field!r}")
    source = plan["capture_source"]
    if not isinstance(source, str) or not source:
        return fail(
            "capture_source_missing",
            "capture_source must name hevi's own browser automation",
        )
    if "codex" in source.lower():
        return fail(
            "capture_source_bound_to_codex",
            "capture_source must not bind to the Codex in-app browser",
        )
    frames = plan["frames"]
    if not isinstance(frames, dict):
        return fail("frames_not_object", "frames must be an object")
    fps = frames.get("fps")
    if not isinstance(fps, (int, float)) or isinstance(fps, bool) or not 1 <= fps <= 60:
        return fail("frames_fps_out_of_range", "frames.fps must be between 1 and 60")
    if frames.get("aspect") not in ASPECTS:
        return fail(
            "frames_aspect_unknown",
            "frames.aspect must be one of: " + ", ".join(ASPECTS),
        )
    for dim in ("width", "height"):
        value = frames.get(dim)
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            return fail(
                "frames_dimension_bad",
                f"frames.{dim} must be a positive integer",
            )
        if value > MAX_DIMENSION:
            return fail(
                "frames_dimension_too_large",
                f"frames.{dim} must not exceed {MAX_DIMENSION}",
            )
    interactions = plan["interactions"]
    if not isinstance(interactions, list) or not interactions:
        return fail(
            "interactions_empty",
            "interactions needs at least one choreographed interaction",
        )
    for interaction in interactions:
        if not isinstance(interaction, dict):
            return fail("interaction_not_object", "each interaction must be an object")
        if interaction.get("type") not in INTERACTION_TYPES:
            return fail(
                "interaction_type_unknown",
                "interaction type must be one of: " + ", ".join(INTERACTION_TYPES),
            )
        if not isinstance(interaction.get("target"), str) or not interaction["target"]:
            return fail("interaction_target_missing", "each interaction needs a target")
        at_s = interaction.get("at_s")
        if not isinstance(at_s, (int, float)) or isinstance(at_s, bool) or at_s < 0:
            return fail(
                "interaction_at_s_bad",
                "each interaction needs a non-negative at_s",
            )
    render = plan["render"]
    if not isinstance(render, dict):
        return fail("render_not_object", "render must be an object")
    if render.get("tool") not in ("pillow+ffmpeg", "ffmpeg"):
        return fail(
            "render_tool_unknown",
            "render.tool must be pillow+ffmpeg or ffmpeg",
        )
    if render.get("ffprobe_check") is not True:
        return fail(
            "ffprobe_check_missing",
            "render must declare ffprobe_check true; the output is verified, not assumed",
        )
    duration = plan["duration_s"]
    if not isinstance(duration, (int, float)) or isinstance(duration, bool) or duration <= 0:
        return fail("duration_not_positive", "duration_s must be a positive number")
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
    report = check_browser_demo_recording(params.get("plan"))
    report_path = out_dir / "browser_demo_recording_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_browser_demo_recording_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.browser_demo_recording_gate",
            kind="line",
            aspects=["16:9", "4:3", "9:16"],
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
                "Browser demo recording gate: screenshots from hevi's own "
                "browser automation, frame parameters, choreographed mouse, "
                "click, follow-zoom and scroll interactions, Pillow plus "
                "ffmpeg render with an ffprobe truth check."
            ),
        )
    )
    return ["qa.browser_demo_recording_gate"]


__all__ = [
    "INTERACTION_TYPES",
    "check_browser_demo_recording",
    "register_browser_demo_recording_gate_capabilities_once",
]
