"""Blemish trim for live-recorded speech (``edit.speech_blemish_trim``).

Pipeline, in order, for a word-level transcript of a real recording:

1. Word-level transcript in, with a start and end time per word.
2. Deletion candidates: filler words (a standalone 嗯 / 呃 / 这个 /
   那个 and the like) and immediately repeated words.
3. Keep-before / keep-after guard: a candidate may only be cut when
   a kept word stands on both sides of it, so the splice has real
   audio to join. A candidate at the very start or end, or with no
   kept neighbour, is blocked, not cut.
4. Risk tiers: low (one short filler between kept words), medium
   (a repetition, or a longer filler), high (long, or blocked by
   the guard). Only approved tiers are cut; high-risk and blocked
   candidates stay in and go on the review checklist.
5. Review checklist: every candidate with its decision and the
   listening checks a human must still do (does the sentence still
   read whole? does the join sound clean?).
6. Keep intervals: the complement of the approved cuts, as splice
   intervals a cutter can apply to the audio.
7. Post-trim captions: provisional captions rebuilt from the kept
   words, retimed past the cuts -- explicitly provisional. The
   finished captions must come from a fresh transcription of the
   trimmed audio; this module does not pretend its rebuild is that
   transcription.

Scope rule, enforced first: this applies only to genuinely
recorded speech. A synthetic (TTS) track has no stumbles to cut,
so asking to trim one is refused with an explanation, not given a
fake edit. Anything that is not a live recording is refused too.
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

FILLERS = {"嗯", "呃", "额", "啊", "这个", "那个", "嗯嗯", "呃呃"}
_LOW_MAX_SEC = 0.6
_MEDIUM_MAX_SEC = 1.5
# A splice needs a little real audio on both sides; a candidate
# touching the edge of the transcript has none on one side.
_APPROVE_DEFAULT = ("low", "medium")


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _validate_words(words: Any) -> list[dict[str, Any]]:
    if not isinstance(words, list) or not words:
        raise CapabilityError(
            "edit.speech_blemish_trim: words must be a non-empty list of "
            "word-level transcript entries"
        )
    cleaned: list[dict[str, Any]] = []
    previous_end: float | None = None
    for index, entry in enumerate(words):
        if not isinstance(entry, dict) or not entry.get("word"):
            raise CapabilityError(
                "edit.speech_blemish_trim: word entry "
                f"{index} is missing its word"
            )
        start, end = entry.get("start_sec"), entry.get("end_sec")
        if not _is_number(start) or not _is_number(end) \
                or float(end) <= float(start):
            raise CapabilityError(
                "edit.speech_blemish_trim: word entry "
                f"{index} ('{entry.get('word')}') needs start_sec < end_sec"
            )
        if previous_end is not None and float(start) < previous_end:
            raise CapabilityError(
                "edit.speech_blemish_trim: word entries must be in time order"
            )
        previous_end = float(end)
        cleaned.append({
            "word": str(entry["word"]),
            "start_sec": float(start),
            "end_sec": float(end),
        })
    return cleaned


def _candidates(words: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group consecutive candidate words into cut segments."""
    flagged: list[int] = []
    for index, entry in enumerate(words):
        if entry["word"] in FILLERS:
            flagged.append(index)
        elif index > 0 and entry["word"] == words[index - 1]["word"]:
            flagged.append(index)
    segments: list[dict[str, Any]] = []
    for index in flagged:
        kind = "filler" if words[index]["word"] in FILLERS else "repetition"
        if segments and segments[-1]["end_index"] == index - 1:
            segments[-1]["end_index"] = index
            segments[-1]["words"].append(words[index]["word"])
        else:
            segments.append({
                "start_index": index, "end_index": index,
                "kind": kind, "words": [words[index]["word"]],
            })
    for segment in segments:
        segment["start_sec"] = words[segment["start_index"]]["start_sec"]
        segment["end_sec"] = words[segment["end_index"]]["end_sec"]
        segment["duration_sec"] = segment["end_sec"] - segment["start_sec"]
    return segments


def plan_trim(
    words: Any,
    *,
    source_kind: str,
    approve_risk_levels: Any = _APPROVE_DEFAULT,
) -> dict[str, Any]:
    """Build the trim plan, or refuse when the scope rule forbids it."""
    if source_kind == "tts":
        raise CapabilityError(
            "edit.speech_blemish_trim: refused -- this track is TTS "
            "synthesis, which has no spoken blemishes to cut. Cutting "
            "it would be a fake edit: there is no stumble, false start, "
            "or filler in synthetic speech to remove, so nothing is cut."
        )
    if source_kind != "live_recording":
        raise CapabilityError(
            "edit.speech_blemish_trim: refused -- only live-recorded "
            f"speech may be trimmed, not source_kind={source_kind!r}. "
            "Name the source as live_recording when it genuinely is one."
        )
    cleaned = _validate_words(words)
    approved_levels = set(approve_risk_levels or ())
    segments = _candidates(cleaned)
    cut_indices: set[int] = set()
    for segment in segments:
        has_before = segment["start_index"] > 0
        has_after = segment["end_index"] < len(cleaned) - 1
        if not (has_before and has_after):
            segment["risk"] = "high"
            segment["blocked"] = True
            segment["block_reason"] = (
                "keep-before/keep-after guard: no kept word on one side "
                "of this candidate, so there is nothing clean to splice to"
            )
        elif segment["duration_sec"] <= _LOW_MAX_SEC \
                and len(segment["words"]) == 1 \
                and segment["kind"] == "filler":
            segment["risk"] = "low"
            segment["blocked"] = False
            segment["block_reason"] = None
        elif segment["duration_sec"] <= _MEDIUM_MAX_SEC:
            segment["risk"] = "medium"
            segment["blocked"] = False
            segment["block_reason"] = None
        else:
            segment["risk"] = "high"
            segment["blocked"] = False
            segment["block_reason"] = None
        segment["decision"] = (
            "approved" if (not segment["blocked"]
                           and segment["risk"] in approved_levels)
            else ("blocked" if segment["blocked"] else "held")
        )
        if segment["decision"] == "approved":
            cut_indices.update(
                range(segment["start_index"], segment["end_index"] + 1))
    kept = [w for i, w in enumerate(cleaned) if i not in cut_indices]
    intervals: list[dict[str, float]] = []
    for entry in kept:
        if intervals and entry["start_sec"] <= intervals[-1]["end_sec"] + 0.25:
            intervals[-1]["end_sec"] = entry["end_sec"]
        else:
            intervals.append({
                "start_sec": entry["start_sec"],
                "end_sec": entry["end_sec"],
            })
    removed_before = 0.0
    provisional: list[dict[str, Any]] = []
    cut_sorted = sorted(cut_indices)
    for index, entry in enumerate(cleaned):
        if index in cut_indices:
            removed_before += entry["end_sec"] - entry["start_sec"]
            continue
        provisional.append({
            "word": entry["word"],
            "start_sec": round(entry["start_sec"] - removed_before, 3),
            "end_sec": round(entry["end_sec"] - removed_before, 3),
        })
    checklist = [
        {
            "segment_words": seg["words"],
            "kind": seg["kind"],
            "risk": seg["risk"],
            "decision": seg["decision"],
            "checks": [
                "Listen to the kept word before and after the cut: "
                "does the join sound clean, with no clipped syllable?",
                "Read the sentence without the cut words: is it still "
                "whole and still true to what was meant?",
            ] + (["Do not cut: blocked by the keep-before/keep-after "
                  "guard; leave this in the film."]
                 if seg["blocked"] else []),
        }
        for seg in segments
    ]
    return {
        "source_kind": source_kind,
        "segments": segments,
        "review_checklist": checklist,
        "kept_words": [w["word"] for w in kept],
        "kept_intervals": intervals,
        "provisional_captions_from_kept_words": provisional,
        "post_trim_steps": [
            "Apply kept_intervals to the audio to produce the trimmed track.",
            "Run a fresh transcription over the trimmed audio.",
            "Replace the provisional captions above with that fresh "
            "transcription before shipping; the provisional captions are "
            "a retiming aid, not a retranscription.",
        ],
        "retranscription_note": "Provisional captions are rebuilt from kept "
            "words only. They are NOT a post-trim retranscription: only "
            "fresh ASR over the trimmed audio counts as one.",
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
             aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    plan = plan_trim(
        params.get("words"),
        source_kind=str(params.get("source_kind", "")),
        approve_risk_levels=params.get("approve_risk_levels")
        or _APPROVE_DEFAULT,
    )
    report_path = out_dir / "speech_blemish_trim_report.json"
    report_path.write_text(
        json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path),
            "segments": len(plan["segments"]),
            "kept_intervals": len(plan["kept_intervals"])},
    )


def register_speech_blemish_trim_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="edit.speech_blemish_trim",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "words": {"type": "array"},
                    "source_kind": {"type": "string"},
                    "approve_risk_levels": {"type": "array",
                                            "items": {"type": "string"}},
                },
                "required": ["words", "source_kind"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            description=(
                "Blemish trim for live-recorded speech only: word-level "
                "transcript to filler/repetition candidates, "
                "keep-before/keep-after guard, low/medium/high risk "
                "tiers, a human review checklist, keep-interval splice "
                "plan, and provisional post-trim captions that must be "
                "replaced by fresh ASR over the trimmed audio. TTS "
                "tracks are refused, not fake-trimmed."
            ),
            line="edit",
            has_media_output=False,
        )
    )
    return ["edit.speech_blemish_trim"]


register_speech_blemish_trim_capabilities_once()
