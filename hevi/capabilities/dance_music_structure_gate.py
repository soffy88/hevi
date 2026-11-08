"""Dance music-structure gate (``qa.dance_music_structure_gate``).

Clean-room restatement of the dance MV methodology (see
``DANCE_MV_METHODOLOGY_ATTRIBUTION.md``): before any dance
phrase is written, the music itself must be measured — tempo,
beat, bar and phrase lengths derived from one BPM, the first
real downbeat located, and the cuts manifest named as the
authority for slice boundaries. Global and local clocks must
never be mixed: a shot carries one basis only. This gate
judges the music record only. It plays nothing, renders
nothing, and spends nothing: ``executed_here`` is always
false.

This is the music-timing increment the Eian story gate does
not cover: ``qa.story_five_standard_gate`` judges the story;
this gate judges the measured music the dance is built on.
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

BPM_MIN = 40
BPM_MAX = 240
TIMECODE_BASES: frozenset[str] = frozenset({"global", "local"})


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_dance_music_structure(music: Any) -> dict[str, Any]:
    """Validate measured music structure for one dance MV.

    Verdicts are ``pass`` / ``fail`` only. The music fails
    when the BPM is missing or outside the measurable range,
    when beat, bar or phrase lengths do not follow from the
    BPM, when the first downbeat has no measured offset,
    when no verified cuts manifest is named, when the
    timecode basis is undeclared or shots mix bases, or
    when any shot time is negative or runs past the total.
    """
    issues: list[dict[str, Any]] = []

    def fail(code: str, detail: str) -> dict[str, Any]:
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [*issues, _issue(code, detail)],
            "executed_here": False,
        }

    if not isinstance(music, dict):
        return fail("music_not_object", "music structure must be a JSON object")
    bpm = music.get("bpm")
    if not isinstance(bpm, (int, float)) or isinstance(bpm, bool):
        return fail("bpm_missing", "music must state its BPM as a number")
    if bpm < BPM_MIN or bpm > BPM_MAX:
        return fail(
            "bpm_out_of_range",
            f"BPM {bpm} is outside the measurable range {BPM_MIN}-{BPM_MAX}",
        )
    beat = music.get("beat_s")
    if not isinstance(beat, (int, float)) or isinstance(beat, bool) or beat <= 0:
        return fail("beat_missing", "music must state its beat length in seconds")
    if abs(beat - 60.0 / bpm) > 0.005:
        return fail(
            "beat_mismatch",
            f"beat {beat}s does not follow from BPM {bpm} (60/BPM)",
        )
    beats_per_bar = music.get("beats_per_bar")
    if not isinstance(beats_per_bar, int) or isinstance(beats_per_bar, bool):
        return fail(
            "beats_per_bar_missing",
            "music must state beats per bar as a whole number",
        )
    bar = music.get("bar_s")
    if not isinstance(bar, (int, float)) or isinstance(bar, bool) or bar <= 0:
        return fail("bar_missing", "music must state its bar length in seconds")
    if abs(bar - beat * beats_per_bar) > 0.005:
        return fail(
            "bar_mismatch",
            "bar length does not follow from beat times beats per bar",
        )
    bars_per_phrase = music.get("bars_per_phrase")
    if not isinstance(bars_per_phrase, int) or isinstance(bars_per_phrase, bool):
        return fail(
            "bars_per_phrase_missing",
            "music must state bars per phrase as a whole number",
        )
    phrase = music.get("phrase_s")
    if not isinstance(phrase, (int, float)) or isinstance(phrase, bool) or phrase <= 0:
        return fail("phrase_missing", "music must state its phrase length in seconds")
    if abs(phrase - bar * bars_per_phrase) > 0.01:
        return fail(
            "phrase_mismatch",
            "phrase length does not follow from bar times bars per phrase",
        )
    offset = music.get("first_downbeat_offset_s")
    if not isinstance(offset, (int, float)) or isinstance(offset, bool) or offset < 0:
        return fail(
            "first_downbeat_missing",
            "music must state the first downbeat offset in seconds",
        )
    manifest = music.get("cuts_manifest")
    if not isinstance(manifest, dict):
        return fail(
            "cuts_manifest_missing",
            "music must name a cuts manifest as the slice authority",
        )
    if not isinstance(manifest.get("source"), str) or not manifest["source"].strip():
        return fail(
            "cuts_manifest_source_missing",
            "cuts manifest must name its source file",
        )
    if manifest.get("verified") is not True:
        return fail(
            "cuts_manifest_unverified",
            "cuts manifest must be verified before it can bound slices",
        )
    basis = music.get("timecode_basis")
    if basis not in TIMECODE_BASES:
        return fail(
            "timecode_basis_unknown",
            "music must declare one timecode basis: global or local",
        )
    total = music.get("total_duration_s")
    if not isinstance(total, (int, float)) or isinstance(total, bool) or total <= 0:
        return fail(
            "total_duration_missing",
            "music must state its total duration in seconds",
        )
    shots = music.get("shots")
    if not isinstance(shots, list) or not shots:
        return fail("shots_missing", "music must carry at least one shot")
    previous_start: float | None = None
    for position, shot in enumerate(shots):
        if not isinstance(shot, dict):
            return fail(
                "shot_not_object",
                f"shot {position} must be an object",
            )
        if shot.get("basis") != basis:
            return fail(
                "timecode_mixed",
                f"shot {position} uses a different timecode basis "
                "than the declared one; global and local never mix",
            )
        start = shot.get("start_s")
        end = shot.get("end_s")
        if not isinstance(start, (int, float)) or isinstance(start, bool):
            return fail(
                "shot_start_missing",
                f"shot {position} must carry its start in seconds",
            )
        if not isinstance(end, (int, float)) or isinstance(end, bool):
            return fail(
                "shot_end_missing",
                f"shot {position} must carry its end in seconds",
            )
        if start < 0:
            return fail(
                "shot_time_negative",
                f"shot {position} starts before zero",
            )
        if end <= start:
            return fail(
                "shot_end_before_start",
                f"shot {position} ends before it starts",
            )
        if end > total:
            return fail(
                "shot_past_total",
                f"shot {position} runs past the total duration",
            )
        if previous_start is not None and start < previous_start:
            return fail(
                "shots_unordered",
                f"shot {position} starts before the previous shot",
            )
        previous_start = start
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
    report = check_dance_music_structure(params.get("music"))
    report_path = out_dir / "dance_music_structure_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_dance_music_structure_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.dance_music_structure_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "music": {"type": "object"},
                },
                "required": ["music"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="oskill",
            description=(
                "Dance music-structure gate: BPM-derived beat, bar "
                "and phrase lengths, first downbeat offset, verified "
                "cuts manifest authority, and one timecode basis only."
            ),
        )
    )
    return ["qa.dance_music_structure_gate"]


__all__ = [
    "BPM_MAX",
    "BPM_MIN",
    "TIMECODE_BASES",
    "check_dance_music_structure",
    "register_dance_music_structure_gate_capabilities_once",
]
