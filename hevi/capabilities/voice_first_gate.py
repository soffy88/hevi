"""Voice-first gate (``qa.voice_first_gate``).

Clean-room rewrite of the *voice-first* discipline of the
3D cartoon tutorial (see CARTOON_TUTORIAL_ATTRIBUTION.md):
the voice track comes first, and the shot table is cut to
it. A render step must refuse a storyboard that has no
audio, or audio with no word-level timing, because there is
then nothing to cut the picture to.

Rules, all judged on the plan only -- no audio is
generated and no real alignment is measured:

* At least one audio segment must be declared, each with
  an id and a positive ``duration_sec``.
* Every shot must name an ``audio_segment_id`` that
  exists; a shot cut to no audio fails.
* Every audio segment must carry word-level timing in
  the ``edit.word_subtitle_contract`` shape (absolute
  source seconds, ordered, non-overlapping words). The
  contract is built with that capability's own builder,
  so its failure contract is this gate's failure
  contract: bad word timing fails here, never silently
  repaired.
* Audio time and storyboard time must agree within
  ``tolerance_sec`` (default 0.5s): the summed audio
  durations against the storyboard's total duration
  (``total_duration_sec``, or the latest shot end).
  A word ending past its segment's declared duration
  also fails.

Alignment is labelled ``planned_not_measured`` throughout,
matching the ``pipeline.code_studio_workflow`` beat-grid
discipline: this gate proves the timing exists on paper,
not that a recording matches it. Real measurement, when
it exists, must say so separately and must never be
inferred from this gate passing.
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
from hevi.capabilities.word_subtitle_contract import build_contract

_Registered = False

DEFAULT_TOLERANCE_SEC = 0.5


def _is_num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def check_voice_first(plan: Any, *, tolerance_sec: float = DEFAULT_TOLERANCE_SEC) -> dict[str, Any]:
    """Judge whether a storyboard is cut to a timed voice track."""
    if not isinstance(plan, dict):
        raise CapabilityError(
            "qa.voice_first_gate: plan must be a JSON object"
        )
    if not _is_num(tolerance_sec) or float(tolerance_sec) < 0:
        raise CapabilityError(
            "qa.voice_first_gate: tolerance_sec must be a non-negative number"
        )
    tolerance = float(tolerance_sec)
    problems: list[str] = []

    segments_raw = plan.get("audio_segments")
    if not isinstance(segments_raw, list) or not segments_raw:
        problems.append(
            "audio_segments: at least one audio segment is required "
            "before rendering; no voice track, no cut"
        )
        segments_raw = []
    segments: dict[str, dict[str, Any]] = {}
    total_audio_sec = 0.0
    contracts: dict[str, Any] = {}
    for index, raw in enumerate(segments_raw):
        if not isinstance(raw, dict):
            problems.append(f"audio_segments[{index}]: must be a JSON object")
            continue
        segment_id = raw.get("id")
        if not isinstance(segment_id, str) or not segment_id.strip():
            problems.append(f"audio_segments[{index}]: id must be a non-empty string")
            continue
        segment_id = segment_id.strip()
        if segment_id in segments:
            problems.append(f"audio_segments: duplicate id {segment_id!r}")
        duration = raw.get("duration_sec")
        if not _is_num(duration) or float(duration) <= 0:
            problems.append(
                f"audio_segments[{segment_id}]: duration_sec must be > 0"
            )
            duration = 0.0
        segments[segment_id] = {"id": segment_id, "duration_sec": float(duration)}
        total_audio_sec += float(duration)
        words = raw.get("words")
        if not isinstance(words, list) or not words:
            problems.append(
                f"audio_segments[{segment_id}]: no word-level timing; "
                "a transcript without word times cannot cut a shot table"
            )
            continue
        transcript = {
            "words": words,
            "source_duration_sec": float(duration) if float(duration) > 0 else None,
        }
        try:
            contract = build_contract(transcript)
        except CapabilityError as exc:
            problems.append(f"audio_segments[{segment_id}]: {exc}")
            continue
        contracts[segment_id] = contract
        if float(duration) > 0 and contract["last_end_sec"] > float(duration) + tolerance:
            problems.append(
                f"audio_segments[{segment_id}]: last word ends at "
                f"{contract['last_end_sec']}s, past the declared "
                f"duration {duration}s"
            )

    shots_raw = plan.get("shots")
    if not isinstance(shots_raw, list) or not shots_raw:
        problems.append("shots: a non-empty shot list is required")
        shots_raw = []
    latest_end = 0.0
    for index, raw in enumerate(shots_raw):
        if not isinstance(raw, dict):
            problems.append(f"shots[{index}]: must be a JSON object")
            continue
        audio_id = raw.get("audio_segment_id")
        if not isinstance(audio_id, str) or not audio_id.strip():
            problems.append(
                f"shots[{index}]: audio_segment_id is required; "
                "every shot must be cut to a voice segment"
            )
        elif audio_id.strip() not in segments:
            problems.append(
                f"shots[{index}]: audio_segment_id {audio_id!r} "
                "names no declared audio segment"
            )
        end = raw.get("end_sec")
        if _is_num(end):
            latest_end = max(latest_end, float(end))

    total = plan.get("total_duration_sec")
    if _is_num(total):
        total_duration = float(total)
    elif latest_end > 0:
        total_duration = latest_end
    else:
        total_duration = 0.0
    if total_duration > 0 and segments:
        drift = abs(total_audio_sec - total_duration)
        if drift > tolerance:
            problems.append(
                f"duration: audio total {total_audio_sec}s vs storyboard "
                f"total {total_duration}s differ by {drift}s, over the "
                f"{tolerance}s tolerance"
            )
    return {
        "ok": not problems,
        "problems": problems,
        "audio_segment_count": len(segments),
        "shot_count": len(shots_raw),
        "total_audio_sec": round(total_audio_sec, 3),
        "total_duration_sec": total_duration,
        "word_contracts": contracts,
        "alignment_basis": "planned_not_measured",
        "measured": False,
        "measurement_note": (
            "word timing exists on paper only; no recording has been "
            "measured against it by this gate"
        ),
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    report = check_voice_first(
        params.get("plan"),
        tolerance_sec=float(params.get("tolerance_sec", DEFAULT_TOLERANCE_SEC)),
    )
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "voice_first_gate_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={
            "report_json": str(report_path),
            "pass": report["ok"],
            "alignment_basis": report["alignment_basis"],
        },
    )


def register_voice_first_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.voice_first_gate",
            kind="line",
            aspects=["16:9", "9:16", "1:1"],
            params_schema={
                "type": "object",
                "properties": {
                    "plan": {"type": "object"},
                    "tolerance_sec": {"type": "number", "minimum": 0},
                },
                "required": ["plan"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Voice-first gate: every shot must name a declared audio "
                "segment, every segment must carry word-level timing in "
                "the word-subtitle-contract shape, and audio and "
                "storyboard totals must agree. Planned timing only; "
                "no audio is generated and no alignment is measured."
            ),
            line="qa",
        )
    )
    return ["qa.voice_first_gate"]


register_voice_first_gate_capabilities_once()
