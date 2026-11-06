"""Dance H3 prompt gate (``qa.dance_h3_prompt_gate``).

Clean-room restatement of the dance MV methodology (see
``DANCE_MV_METHODOLOGY_ATTRIBUTION.md``): a prompt for
one segment must stand alone. Its six sections follow
the house six-section format exactly — subject
definitions, summary, retention analysis, detailed
description, overall soundscape, non-diegetic music —
and no other section name belongs there. The supplied
audio is the only sound: it is used unchanged, never
restarted or replaced. Global and local clocks never
mix. Sung lyrics stay in the soundtrack and are never
forced into lip-sync; only real spoken words get lip
movement, in the speaker's own language, with the face
held still and readable. No internal library code may
leak into the prompt. This gate judges the prompt record
only. It calls no model, renders nothing, and spends
nothing: ``executed_here`` is always false.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)
from hevi.capabilities.scene_reference import H3_SECTIONS

_Registered = False

# The house six-section format, single-sourced from
# scene_reference. The provider-layer field
# integrated_multimodal_description is not one of them
# and is refused here.
SIX_SECTIONS: frozenset[str] = frozenset(H3_SECTIONS)
TIMECODE_BASES: frozenset[str] = frozenset({"global", "local"})
CROSS_REFERENCES: tuple[str, ...] = ("same as above", "as above", "同上")
_CODE_SHAPE = re.compile(r"^[A-Za-z]\d{1,2}$")
_CJK = re.compile(r"[\u4e00-\u9fff]")


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def _has_library_code(value: Any) -> bool:
    """True when any key or bare code-shaped value is present."""
    if isinstance(value, dict):
        return any(
            key == "library_code" or _has_library_code(item) for key, item in value.items()
        ) or any(isinstance(key, str) and bool(_CODE_SHAPE.match(key)) for key in value)
    if isinstance(value, list):
        return any(_has_library_code(item) for item in value)
    return isinstance(value, str) and bool(_CODE_SHAPE.match(value))


def _has_cross_reference(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in CROSS_REFERENCES)


def check_dance_h3_prompt(prompt: Any) -> dict[str, Any]:
    """Validate one self-contained H3 segment prompt.

    Verdicts are ``pass`` / ``fail`` only. The prompt fails
    when its sections are not exactly the six house
    sections, when any section mixes in another language
    or points back at another segment, when the audio is
    not the one supplied audio used unchanged, when the
    timecode basis is undeclared or shots mix bases, when
    spoken words and dance fight over the same face, or
    when any internal library code leaks in.
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
        return fail("prompt_not_object", "H3 prompt must be a JSON object")
    if _has_library_code(prompt):
        return fail(
            "library_code_refused",
            "internal library codes are refused here; the source "
            "library was never supplied, so prompts carry plain "
            "language only",
        )
    sections = prompt.get("sections")
    if not isinstance(sections, dict):
        return fail(
            "sections_missing",
            "prompt must carry its six sections",
        )
    if set(sections) != set(SIX_SECTIONS):
        return fail(
            "sections_not_six",
            "prompt sections must be exactly the six house sections; "
            "no other section name belongs here",
        )
    for name, text in sections.items():
        if not isinstance(text, str) or not text.strip():
            return fail(
                "section_empty",
                f"section {name} must be written out",
            )
        if _CJK.search(text):
            return fail(
                "mixed_language",
                f"section {name} mixes another language into the English prompt text",
            )
        if _has_cross_reference(text):
            return fail(
                "cross_reference",
                f"section {name} points back at another segment; each segment stands alone",
            )
    audio = prompt.get("audio")
    if not isinstance(audio, dict):
        return fail(
            "audio_missing",
            "prompt must name its one supplied audio",
        )
    if audio.get("source") != "audio_1":
        return fail(
            "audio_not_authoritative",
            "the supplied audio is the only sound source",
        )
    if audio.get("unchanged") is not True:
        return fail(
            "audio_changed",
            "the supplied audio must be used unchanged, never restarted, retimed or replaced",
        )
    basis = prompt.get("timecode_basis")
    if basis not in TIMECODE_BASES:
        return fail(
            "timecode_basis_unknown",
            "prompt must declare one timecode basis: global or local",
        )
    shots = prompt.get("shots")
    if not isinstance(shots, list) or not shots:
        return fail("shots_missing", "prompt must carry at least one shot")
    for position, shot in enumerate(shots):
        if not isinstance(shot, dict):
            return fail(
                "shot_not_object",
                f"shot {position} must be an object",
            )
        if shot.get("basis") != basis:
            return fail(
                "timecode_mixed",
                f"shot {position} uses a different timecode basis than the declared one",
            )
        for field in ("start_s", "end_s"):
            value = shot.get(field)
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                return fail(
                    "shot_time_missing",
                    f"shot {position} must carry {field} in seconds",
                )
        if shot["end_s"] <= shot["start_s"]:
            return fail(
                "shot_end_before_start",
                f"shot {position} ends before it starts",
            )
        description = shot.get("description", "")
        if isinstance(description, str) and _has_cross_reference(description):
            return fail(
                "cross_reference",
                f"shot {position} points back at another segment",
            )
    dance_only = prompt.get("dance_only", False)
    spoken = prompt.get("spoken")
    if dance_only is True:
        if spoken is not None:
            return fail(
                "dance_only_spoken_conflict",
                "a dance-only segment carries no spoken words",
            )
        detailed = sections.get("detailed_description", "")
        if "no dialogue" not in detailed.lower():
            return fail(
                "dialogue_statement_missing",
                "a dance-only segment must state that it has no dialogue",
            )
    if spoken is not None:
        if not isinstance(spoken, dict):
            return fail(
                "spoken_not_object",
                "spoken words must be an object",
            )
        dialogue = spoken.get("dialogue")
        if not isinstance(dialogue, str) or not dialogue.strip():
            return fail(
                "spoken_dialogue_missing",
                "spoken words must carry the dialogue",
            )
        if not dialogue.startswith("<d>["):
            return fail(
                "spoken_tag_wrong",
                "spoken dialogue must sit inside a <d>[Language] tag in its own language",
            )
        if spoken.get("requires_front_closeup") is not True:
            return fail(
                "spoken_face_unstable",
                "spoken words need a stable front close-up with the mouth unobstructed",
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
    report = check_dance_h3_prompt(params.get("prompt"))
    report_path = out_dir / "dance_h3_prompt_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_dance_h3_prompt_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.dance_h3_prompt_gate",
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
                "Dance H3 prompt gate: exactly the six house "
                "sections, one supplied audio used unchanged, one "
                "timecode basis, spoken words separated from dance, "
                "no library codes."
            ),
        )
    )
    return ["qa.dance_h3_prompt_gate"]


__all__ = [
    "CROSS_REFERENCES",
    "SIX_SECTIONS",
    "TIMECODE_BASES",
    "check_dance_h3_prompt",
    "register_dance_h3_prompt_gate_capabilities_once",
]
