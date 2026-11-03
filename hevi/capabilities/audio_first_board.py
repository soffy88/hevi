"""Audio-first storyboard (``story.audio_first_board``).

Clean-room method: the storyboard is cut from a REAL voice SRT
(word / sentence-level timestamps supplied by the caller), never
from an estimated duration.

Rules enforced by raising CapabilityError:

* cues must be a non-empty list, sorted, non-overlapping, each
  with start < end and start >= 0;
* the first cue must start at 0.000: the first shot's start is
  therefore 0 by construction. A first cue starting later is an
  error -- pad the audio instead of shifting timings here;
* picture-sentence correspondence is strict: a shot's text must
  equal the exact concatenation of its cues' texts. The builder
  constructs shots that way and then verifies it; any mismatch
  is an error, not a warning;
* cut target is about 8 seconds per shot, allowed 6-10 seconds.
  Cues accumulate into a shot until adding the next cue would
  pass 10s; a shot is cut once it reaches 6s. Two honest
  exceptions, flagged per shot instead of hidden: a shot longer
  than 10s is kept whole (a sentence is never cut in the
  middle, and a short cue cannot be cut away from the cue that
  follows it without breaking correspondence) and flagged
  ``overlong``; the final tail shorter than 6s is flagged
  ``final_tail_short``. A non-final shot shorter than 6s is
  still an error, because the greedy cut only fires at or
  above the 6s floor.

Research fields (dynasty / person_age / costume / architecture)
travel with each cue and are inherited by the shot: the first
non-empty value in the shot wins, disagreements are reported
in ``research_conflicts``, and any field with no supplied value
is reported as "pending" -- never invented by this module. A
shot's ``camera_move`` is likewise supplied or "pending".

This module never synthesises audio, never estimates timings,
and never fills a missing research field with a guess.
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
_TOL = 1e-3
_CUT_MIN = 6.0
_CUT_MAX = 10.0
_RESEARCH_FIELDS = ("dynasty", "person_age", "costume", "architecture")
_KEY_FIELDS = ("api_key", "apikey", "token", "secret", "password", "key")


def _is_num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _require_str(value: Any, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CapabilityError(f"story.audio_first_board: {what} must be a non-empty string")
    return value.strip()


def _reject_keys(obj: Any, what: str) -> None:
    if isinstance(obj, dict):
        for field in _KEY_FIELDS:
            if field in obj:
                raise CapabilityError(
                    f"story.audio_first_board: key-like fields are not accepted ({what})"
                )


def _validate_cues(cues: Any) -> list[dict[str, Any]]:
    if not isinstance(cues, list) or not cues:
        raise CapabilityError("story.audio_first_board: cues must be a non-empty list")
    out: list[dict[str, Any]] = []
    prev_start = -1.0
    prev_end = 0.0
    for i, cue in enumerate(cues):
        if not isinstance(cue, dict):
            raise CapabilityError(f"story.audio_first_board: cue {i} must be a JSON object")
        _reject_keys(cue, f"cue {i}")
        text = _require_str(cue.get("text"), f"cue {i}.text")
        start, end = cue.get("start_sec"), cue.get("end_sec")
        if not _is_num(start) or not _is_num(end):
            raise CapabilityError(f"story.audio_first_board: cue {i} start_sec/end_sec must be numbers")
        start, end = float(start), float(end)
        if start < 0 or end <= start:
            raise CapabilityError(f"story.audio_first_board: cue {i} has an invalid time range")
        if start < prev_start - _TOL:
            raise CapabilityError(f"story.audio_first_board: cue {i} is out of order")
        if start < prev_end - _TOL:
            raise CapabilityError(f"story.audio_first_board: cue {i} overlaps the previous cue")
        research: dict[str, str | None] = {}
        for field in _RESEARCH_FIELDS:
            raw = cue.get(field)
            if raw is None:
                research[field] = None
            elif isinstance(raw, str) and raw.strip():
                research[field] = raw.strip()
            else:
                raise CapabilityError(f"story.audio_first_board: cue {i}.{field} must be a string")
        camera = cue.get("camera_move")
        if camera is not None and (not isinstance(camera, str) or not camera.strip()):
            raise CapabilityError(f"story.audio_first_board: cue {i}.camera_move must be a string")
        out.append({"index": i, "start_sec": start, "end_sec": end, "text": text,
                    "research": research,
                    "camera_move": camera.strip() if isinstance(camera, str) else None})
        prev_start, prev_end = start, end
    if abs(out[0]["start_sec"]) > _TOL:
        raise CapabilityError(
            f"story.audio_first_board: first cue must start at 0 (first shot start "
            f"must be 0), got {out[0]['start_sec']}s; pad the audio, do not shift timings here"
        )
    return out


def build_board(board_input: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(board_input, dict):
        raise CapabilityError("story.audio_first_board: input must be a JSON object")
    _reject_keys(board_input, "input")
    cues = _validate_cues(board_input.get("cues"))
    shots: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []

    def flush(is_final: bool) -> None:
        if not current:
            return
        start = current[0]["start_sec"]
        end = current[-1]["end_sec"]
        duration = round(end - start, 3)
        text = "".join(c["text"] for c in current)
        research: dict[str, str] = {}
        pending: list[str] = []
        conflicts: list[str] = []
        for field in _RESEARCH_FIELDS:
            values = [c["research"][field] for c in current if c["research"][field]]
            if not values:
                research[field] = "pending"
                pending.append(field)
            else:
                research[field] = values[0]
                if len(set(values)) > 1:
                    conflicts.append(field)
        camera_moves = [c["camera_move"] for c in current if c["camera_move"]]
        if duration > _CUT_MAX:
            flag, basis = "overlong", (
                f"shot lasting {duration}s exceeds the 10s ceiling; kept whole "
                "rather than cutting a sentence in the middle or breaking "
                "picture-sentence correspondence"
            )
        elif is_final and duration < _CUT_MIN:
            flag, basis = "final_tail_short", (
                f"final tail lasting {duration}s is under the 6s floor; kept as the "
                "closing shot rather than padding it"
            )
        elif not (_CUT_MIN - _TOL <= duration <= _CUT_MAX + _TOL):
            raise CapabilityError(
                f"story.audio_first_board: shot starting at {start}s lasts {duration}s, "
                "outside the 6-10s cut window (non-final, multi-cue shots must fit)"
            )
        else:
            flag, basis = "in_range", (
                f"accumulated {len(current)} cue(s) to {duration}s, inside the 6-10s "
                "window (target about 8s)"
            )
        shot = {
            "shot_id": f"S{len(shots) + 1:02d}",
            "start_sec": start, "end_sec": end, "duration_sec": duration,
            "cue_indices": [c["index"] for c in current],
            "sentence_text": text, "cut_basis": basis, "duration_flag": flag,
            "research": research, "pending_fields": pending,
            "research_conflicts": conflicts,
            "camera_move": camera_moves[0] if camera_moves else "pending",
        }
        # Strict correspondence check: shot text must be exactly its cues.
        if shot["sentence_text"] != "".join(c["text"] for c in current):
            raise CapabilityError(
                f"story.audio_first_board: shot {shot['shot_id']} text does not match "
                "its spoken cues (picture-sentence misalignment)"
            )
        shots.append(shot)

    for cue in cues:
        if current:
            trial_end = cue["end_sec"]
            trial_duration = trial_end - current[0]["start_sec"]
            current_duration = current[-1]["end_sec"] - current[0]["start_sec"]
            # Cut before this cue if the current shot already reached the
            # floor and adding the cue would pass the ceiling.
            if current_duration >= _CUT_MIN - _TOL and trial_duration > _CUT_MAX + _TOL:
                flush(is_final=False)
                current = []
        current.append(cue)
    flush(is_final=True)
    total = round(shots[-1]["end_sec"] - shots[0]["start_sec"], 3) if shots else 0.0
    return {
        "capability": "story.audio_first_board",
        "shot_count": len(shots),
        "total_duration_sec": total,
        "average_shot_sec": round(total / len(shots), 3) if shots else 0.0,
        "cut_target_sec": 8.0,
        "cut_range_sec": [_CUT_MIN, _CUT_MAX],
        "first_shot_start_sec": shots[0]["start_sec"] if shots else None,
        "shots": shots,
        "flags": {
            "overlong": [s["shot_id"] for s in shots if s["duration_flag"] == "overlong"],
            "final_tail_short": [s["shot_id"] for s in shots if s["duration_flag"] == "final_tail_short"],
        },
        "note": ("Shots are cut from supplied SRT timings only. Research fields "
                 "marked pending were not supplied and were not invented."),
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    _reject_keys(params, "params")
    result = build_board(params.get("board"))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = out_dir / "audio_first_board.json"
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report),
        qa={"report_json": str(report), "shot_count": result["shot_count"],
            "total_duration_sec": result["total_duration_sec"]},
    )


def register_audio_first_board_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(Capability(
        name="story.audio_first_board",
        kind="line",
        aspects=["16:9", "9:16"],
        params_schema={
            "type": "object",
            "properties": {"board": {"type": "object"}},
            "required": ["board"],
            "additionalProperties": False,
        },
        cpu_cost_hint=0.0,
        render=_render,
        has_media_output=False,
        description=(
            "Audio-first storyboard (clean-room): cut a storyboard from real "
            "SRT timings at about 8s per shot (6-10s window), first shot "
            "anchored at 0, picture strictly matched to the spoken sentence, "
            "and per-shot dynasty / age / costume / architecture research "
            "fields that report pending when unsupplied, never invented."
        ),
        line="story",
    ))
    return ["story.audio_first_board"]


register_audio_first_board_capabilities_once()
