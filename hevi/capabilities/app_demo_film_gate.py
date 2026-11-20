"""App demo film gate (``qa.app_demo_film_gate``).

hevi's own method increment for an App / SaaS demo film:
record the operation, analyze the frames, write the narration,
voice it, frame the device, add background music, assemble the
film. The post linked ``alwaysmavs/app-demo-agent`` for this
function, but that repository does not exist (checked
2026-11-20, see ``VIDEO_SKILLS_10_ATTRIBUTION.md``), so this
gate is written from hevi's own pipeline, not from any upstream
file; no upstream code appears in it.

The talkback film gate (``qa.talkback_film_gate``) already owns
the five-step recorded-talkback method, and HyperFrames /
Remotion already own the motion layer. This gate therefore
checks only the demo-film increments: the seven steps in
order, each step verifiable on its own, a declared device
frame, a declared division of labour naming which parts reuse
talkback, HyperFrames, or Remotion and which are new, and a
voiceover with an authorization proof when a voice is used.
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

STEPS = (
    "record_operation",
    "analyze_frames",
    "narration",
    "voiceover",
    "device_frame",
    "bgm",
    "assemble",
)
REUSE_LINES = ("talkback", "hyperframes", "remotion")


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_app_demo_film(plan: Any) -> dict[str, Any]:
    """Validate an App demo film plan.

    Verdicts are ``pass`` / ``fail`` only. A plan fails when
    it is not an object, when any of the seven steps is
    missing, when the steps run out of order, when a step is
    not verifiable on its own, when the device frame is not
    declared, when the division of labour does not name a
    reuse line, or when a voiceover lacks an authorization
    proof or names ElevenLabs or a clone mode.
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
        return fail("plan_not_object", "demo film plan must be a JSON object")
    if "elevenlabs" in json.dumps(plan, ensure_ascii=False).lower():
        return fail(
            "elevenlabs_not_accepted",
            "ElevenLabs is never accepted in a demo film; voiceover uses authorized voices only",
        )
    for field in ("steps", "step_order", "device_frame", "division_of_labour"):
        if field not in plan:
            return fail("plan_field_missing", f"demo film plan must carry {field!r}")
    steps = plan["steps"]
    if not isinstance(steps, dict):
        return fail("steps_missing", "a seven-step declaration is required")
    for step in STEPS:
        if steps.get(step) is not True:
            return fail(
                "step_missing",
                f"step {step!r} is missing from the demo film plan",
            )
    if plan.get("step_order") != list(STEPS):
        return fail(
            "step_order_wrong",
            "the steps must run record_operation, analyze_frames, narration, "
            "voiceover, device_frame, bgm, assemble, in that order",
        )
    if plan.get("each_step_verifiable") is not True:
        return fail(
            "step_not_verifiable",
            "every step must be verifiable on its own",
        )
    device_frame = plan["device_frame"]
    if not isinstance(device_frame, dict):
        return fail("device_frame_not_object", "device_frame must be an object")
    if not isinstance(device_frame.get("device"), str) or not device_frame["device"]:
        return fail("device_frame_device_missing", "device_frame must name a device")
    if device_frame.get("frame") is not True:
        return fail(
            "device_frame_missing",
            "device_frame must declare frame true; the device border is part of the film",
        )
    division = plan["division_of_labour"]
    if not isinstance(division, str) or not division.strip():
        return fail(
            "division_of_labour_missing",
            "declare which demo-film parts reuse talkback, hyperframes, or remotion",
        )
    if not any(line in division for line in REUSE_LINES):
        return fail(
            "division_of_labour_unknown_line",
            "division_of_labour must name at least one reuse line: "
            "talkback, hyperframes, or remotion",
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
        if voice.get("clone") is True or voice.get("mode") == "clone":
            return fail(
                "clone_not_accepted",
                "clone mode is never accepted in a demo film",
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
    report = check_app_demo_film(params.get("plan"))
    report_path = out_dir / "app_demo_film_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_app_demo_film_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.app_demo_film_gate",
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
                "App demo film gate: record operation, analyze frames, "
                "narration, voiceover, device frame, bgm, assemble in order, "
                "each step verifiable, device frame declared, division of "
                "labour naming the talkback, HyperFrames, or Remotion reuse; "
                "voiceover needs an authorization proof."
            ),
        )
    )
    return ["qa.app_demo_film_gate"]


__all__ = [
    "STEPS",
    "check_app_demo_film",
    "register_app_demo_film_gate_capabilities_once",
]
