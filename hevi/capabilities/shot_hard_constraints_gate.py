"""Shot hard-constraints gate (``qa.shot_hard_constraints_gate``).

Clean-room restatement of the per-shot hard limits described in
the Infinite Creation review (see
``INFINITE_CREATION_ATTRIBUTION.md``): a single generation unit
is short, carries at most two speakers, at most three reference
audio segments and at most nine reference images, and its dialogue
fits its duration at the house rate of five characters per second
(the rate is restated from the reviewed method; it is a planning
budget, not a measured speech rate).

Two house rules sit on top of the reviewed limits and are never
relaxed here. First, any frame count a caller declares must lie
on hevi's 5+17k continuation grid (see
``qa.continuation_grid_gate``): the reviewed template's 120-frame
plan is off-grid and fails here. Second, two LoRAs in series
always fail: hevi never mixes LoRA families in one generation,
and a plan that stacks them is not generation-ready.

This module judges shot plans only. It never generates, never
calls a model, and never touches a budget.
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

MIN_DURATION_S = 2.0
MAX_DURATION_S = 15.0
CHARS_PER_SECOND = 5
MAX_SPEAKERS = 2
MAX_REFERENCE_AUDIO = 3
MAX_REFERENCE_IMAGES = 9
GRID_BASE = 5
GRID_STEP = 17


def _issue(code: str, detail: str, **extra: Any) -> dict[str, Any]:
    issue = {"code": code, "detail": f"qa.shot_hard_constraints_gate: {detail}"}
    issue.update(extra)
    return issue


def check_shot_constraints(shot: Any) -> dict[str, Any]:
    """Judge one shot plan against the hard limits.

    ``shot`` carries ``duration_s`` and may carry
    ``dialogue_text``, ``speakers``, ``reference_audio_segments``,
    ``reference_images``, ``fps`` and ``loras``. Verdict ``pass``
    means every declared limit holds and every declared frame
    count is on the 5+17k grid. A missing duration is a failure,
    not an assumption.
    """
    if not isinstance(shot, dict):
        raise CapabilityError("shot plan must be an object")
    issues: list[dict[str, Any]] = []
    duration = shot.get("duration_s")
    if not isinstance(duration, (int, float)) or duration <= 0:
        raise CapabilityError("shot plan requires duration_s > 0")
    if duration < MIN_DURATION_S or duration > MAX_DURATION_S:
        issues.append(
            _issue(
                "duration_out_of_range",
                f"duration {duration}s outside [{MIN_DURATION_S}, {MAX_DURATION_S}]s",
            )
        )
    dialogue = shot.get("dialogue_text", "")
    if not isinstance(dialogue, str):
        raise CapabilityError("dialogue_text must be a string when present")
    chars = len("".join(dialogue.split()))
    budget = int(duration * CHARS_PER_SECOND)
    if chars > budget:
        issues.append(
            _issue(
                "dialogue_over_budget",
                f"dialogue {chars} chars exceeds {budget} chars for {duration}s",
                chars=chars,
                budget=budget,
            )
        )
    speakers = shot.get("speakers", [])
    if not isinstance(speakers, list):
        raise CapabilityError("speakers must be a list when present")
    if len(speakers) > MAX_SPEAKERS:
        issues.append(
            _issue("too_many_speakers", f"{len(speakers)} speakers exceeds {MAX_SPEAKERS}")
        )
    audio_refs = shot.get("reference_audio_segments", [])
    if not isinstance(audio_refs, list):
        raise CapabilityError("reference_audio_segments must be a list when present")
    if len(audio_refs) > MAX_REFERENCE_AUDIO:
        issues.append(
            _issue(
                "too_many_reference_audio",
                f"{len(audio_refs)} reference audio segments exceeds {MAX_REFERENCE_AUDIO}",
            )
        )
    image_refs = shot.get("reference_images", [])
    if not isinstance(image_refs, list):
        raise CapabilityError("reference_images must be a list when present")
    if len(image_refs) > MAX_REFERENCE_IMAGES:
        issues.append(
            _issue(
                "too_many_reference_images",
                f"{len(image_refs)} reference images exceeds {MAX_REFERENCE_IMAGES}",
            )
        )
    fps = shot.get("fps")
    frame_count = None
    if fps is not None:
        if not isinstance(fps, (int, float)) or fps <= 0:
            raise CapabilityError("fps must be > 0 when present")
        frame_count = round(duration * fps)
        if (frame_count - GRID_BASE) % GRID_STEP != 0:
            issues.append(
                _issue(
                    "off_grid",
                    f"frame count {frame_count} ({duration}s at {fps}fps) is not on the 5+17k grid",
                    frame_count=frame_count,
                )
            )
    loras = shot.get("loras", [])
    if not isinstance(loras, list):
        raise CapabilityError("loras must be a list when present")
    if len(loras) > 1:
        issues.append(
            _issue(
                "dual_lora_series",
                f"{len(loras)} LoRAs in series; hevi never mixes LoRA families in one generation",
            )
        )
    for lora in loras:
        if isinstance(lora, dict):
            strength = lora.get("strength")
            if isinstance(strength, (int, float)) and strength > 1.0:
                issues.append(
                    _issue("lora_strength_over_one", f"LoRA strength {strength} exceeds 1.0")
                )
    verdict = "fail" if issues else "pass"
    return {
        "ok": verdict != "fail",
        "verdict": verdict,
        "issues": issues,
        "not_checked": [],
        "duration_s": duration,
        "frame_count": frame_count,
        "dialogue_chars": chars,
        "dialogue_budget": budget,
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_shot_constraints(params.get("shot"))
    report_path = out_dir / "shot_hard_constraints.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_shot_hard_constraints_gate_capabilities_once() -> list[str]:
    """Register ``qa.shot_hard_constraints_gate`` on the unified registry (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.shot_hard_constraints_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "shot": {"type": "object"},
                },
                "required": ["shot"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Shot hard-constraints gate: 2-15s duration, dialogue within "
                "five chars per second, at most two speakers, three reference "
                "audio segments and nine reference images; frame counts must "
                "lie on the 5+17k grid and two LoRAs in series always fail."
            ),
        )
    )
    return ["qa.shot_hard_constraints_gate"]


__all__ = ["check_shot_constraints", "register_shot_hard_constraints_gate_capabilities_once"]
