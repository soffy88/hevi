"""Seven-section video prompt gate (``qa.seven_section_prompt_gate``).

Clean-room restatement of the Eian short-film workflow
(see ``EIAN_WORKFLOW_ATTRIBUTION.md``): a video prompt
that leaves anything to the model will be filled in by
the model. Seven sections are required here, in the
reviewer's own words — style, camera, composition and
palette, characters, second-by-second action, sound, and
constraints. The second-by-second part must open frozen
on the first frame for the first 0.2 seconds and end
frozen on the last frame for the final 0.3 seconds, and
every character's look, clothes and fixed props must be
written down, not left open. This gate judges the prompt
record only. It generates no video and spends nothing:
``executed_here`` is always false.
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

SECTIONS: tuple[str, ...] = (
    "style",
    "camera",
    "composition_palette",
    "characters",
    "per_second",
    "sound",
    "constraints",
)
OPENING_FREEZE_S = 0.2
ENDING_FREEZE_S = 0.3


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_seven_section_prompt(prompt: Any) -> dict[str, Any]:
    """Validate a seven-section video prompt.

    Verdicts are ``pass`` / ``fail`` only. A prompt fails
    when a section is missing, when the second-by-second
    part does not open frozen for 0.2 seconds or end frozen
    for 0.3 seconds on the last frame, when a character's
    look, clothes or fixed props are not written down, when
    a sound has no visible cause, or when the constraints
    do not ban on-screen text and watermarks.
    """
    issues: list[dict[str, Any]] = []

    def fail(code: str, detail: str) -> dict[str, Any]:
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [*issues, _issue(code, detail)],
            "executed_here": False,
        }

    if not isinstance(prompt, dict):
        return fail("prompt_not_object", "prompt must be a JSON object")
    for section in SECTIONS:
        value = prompt.get(section)
        if value is None or (isinstance(value, (str, list, dict)) and not value):
            return fail(
                "section_missing",
                f"seven-section prompt is missing its {section} section",
            )
    characters = prompt.get("characters")
    if not isinstance(characters, list) or not characters:
        return fail(
            "characters_missing",
            "prompt needs a non-empty characters list",
        )
    for position, character in enumerate(characters):
        if not isinstance(character, dict):
            return fail(
                "character_not_object",
                f"character {position} must be an object",
            )
        for field in ("look", "outfit", "fixed_props"):
            value = character.get(field)
            if not isinstance(value, (str, list)) or not value:
                return fail(
                    "character_not_locked",
                    f"character {position} must write down its {field}",
                )
    per_second = prompt.get("per_second")
    if not isinstance(per_second, list) or not per_second:
        return fail(
            "per_second_missing",
            "prompt needs a non-empty second-by-second action list",
        )
    first = per_second[0]
    if not isinstance(first, dict):
        return fail("per_second_not_object", "per-second entries must be objects")
    if first.get("start_s") != 0 or first.get("hold") is not True:
        return fail(
            "opening_not_frozen",
            "the first 0.2 seconds must hold still, identical to the first frame",
        )
    if first.get("end_s") != OPENING_FREEZE_S:
        return fail(
            "opening_freeze_length",
            "the opening hold must cover exactly the first 0.2 seconds",
        )
    last = per_second[-1]
    if not isinstance(last, dict):
        return fail("per_second_not_object", "per-second entries must be objects")
    if last.get("hold_tail") is not True:
        return fail(
            "ending_not_frozen",
            "the final 0.3 seconds must hold still, identical to the last frame",
        )
    duration = prompt.get("duration_s")
    if isinstance(duration, (int, float)):
        if last.get("end_s") != duration:
            return fail(
                "per_second_duration_mismatch",
                "the second-by-second list must end at the stated duration",
            )
        if last.get("start_s") != duration - ENDING_FREEZE_S:
            return fail(
                "ending_freeze_length",
                "the closing hold must cover exactly the final 0.3 seconds",
            )
    sound = prompt.get("sound")
    if not isinstance(sound, dict):
        return fail("sound_not_object", "sound section must be an object")
    audible = sound.get("audible")
    if isinstance(audible, list):
        for position, item in enumerate(audible):
            if not isinstance(item, dict):
                return fail(
                    "sound_not_object",
                    f"sound item {position} must be an object",
                )
            if item.get("visible_cause") is not True:
                return fail(
                    "sound_without_visible_cause",
                    f"sound item {position} has no visible cause in frame",
                )
    constraints = prompt.get("constraints")
    if not isinstance(constraints, dict):
        return fail("constraints_not_object", "constraints section must be an object")
    if constraints.get("no_text") is not True:
        return fail(
            "constraint_text_not_banned",
            "constraints must ban on-screen text",
        )
    if constraints.get("no_watermark") is not True:
        return fail(
            "constraint_watermark_not_banned",
            "constraints must ban watermarks",
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
    report = check_seven_section_prompt(params.get("prompt"))
    report_path = out_dir / "seven_section_prompt_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_seven_section_prompt_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.seven_section_prompt_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "prompt": {"type": "object"},
                },
                "required": ["prompt"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="oskill",
            description=(
                "Seven-section video prompt gate: style, camera, "
                "composition and palette, characters, second-by-second "
                "action with frozen open and close, sound with visible "
                "causes, constraints banning text and watermarks."
            ),
        )
    )
    return ["qa.seven_section_prompt_gate"]


__all__ = [
    "ENDING_FREEZE_S",
    "OPENING_FREEZE_S",
    "SECTIONS",
    "check_seven_section_prompt",
    "register_seven_section_prompt_gate_capabilities_once",
]
