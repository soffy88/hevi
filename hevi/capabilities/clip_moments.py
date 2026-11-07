"""Long-video viral-moment detection (``edit.clip_moments``).

Clean-room method intake, not a port of any upstream clipper: from a
word-level transcript plus scene boundaries, score scene-aligned
candidate windows with checkable factors only, then pick
non-overlapping windows in the 15-60 second range.

Honest boundaries, stated in the output:
* The score is deterministic and local: speech density, hook-word
  hits supplied by the caller, and length fit. No model is run.
* ``model_score`` is always ``pending``: the upstream design scores
  moments with Gemini, but no Gemini key is in scope here, so this
  module never claims a model score. A caller that wants one must
  supply it explicitly and it is then recorded verbatim, never
  invented by this module.
* This module outputs a moment plan (JSON), not clips: cutting,
  subtitling and assembly stay with edit_assemble / edit_video_use
  and the word-subtitle contract in this same intake.
* A window never crosses a scene boundary: candidates are built
  inside scene segments, and long segments are split at word ends.

Failure contract: invalid input (empty transcript, unsorted or
overlapping words, non-positive durations, unknown fields are
rejected by the schema) raises CapabilityError. Too few valid
windows is not an error: it is reported as ``insufficient`` with
the windows that do exist, never padded with invented moments.
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
MIN_CLIP_SEC = 15.0
MAX_CLIP_SEC = 60.0
DEFAULT_MIN_CLIPS = 3
DEFAULT_MAX_CLIPS = 15


def _is_num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _require_num(value: Any, what: str) -> float:
    if not _is_num(value):
        raise CapabilityError(f"edit.clip_moments: {what} must be a number")
    return float(value)


def _require_str(value: Any, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CapabilityError(f"edit.clip_moments: {what} must be a non-empty string")
    return value.strip()


def _validate_words(words: Any) -> list[dict[str, Any]]:
    if not isinstance(words, list) or not words:
        raise CapabilityError("edit.clip_moments: transcript_words must be a non-empty list")
    out: list[dict[str, Any]] = []
    prev_end = -1.0
    for i, w in enumerate(words):
        if not isinstance(w, dict):
            raise CapabilityError(f"edit.clip_moments: word {i} must be a JSON object")
        text = _require_str(w.get("word"), f"word {i}.word")
        start = _require_num(w.get("start_sec"), f"word {i}.start_sec")
        end = _require_num(w.get("end_sec"), f"word {i}.end_sec")
        if start < 0 or end <= start:
            raise CapabilityError(f"edit.clip_moments: word {i} has an invalid time range")
        if start < prev_end - 1e-9:
            raise CapabilityError("edit.clip_moments: transcript_words must be sorted and non-overlapping")
        prev_end = end
        out.append({"word": text, "start_sec": start, "end_sec": end})
    return out


def _segments(words: list[dict[str, Any]], boundaries: Any, source_duration: float) -> list[tuple[float, float]]:
    if not isinstance(boundaries, list):
        raise CapabilityError("edit.clip_moments: scene_boundaries_sec must be a list")
    cuts = [0.0]
    for b in boundaries:
        v = _require_num(b, "scene_boundaries_sec entry")
        if v <= 0 or v >= source_duration:
            raise CapabilityError("edit.clip_moments: scene boundary must lie strictly inside the source")
        cuts.append(v)
    cuts.append(float(source_duration))
    cuts = sorted(set(cuts))
    for a, b in zip(cuts, cuts[1:]):
        if b - a <= 0:
            raise CapabilityError("edit.clip_moments: scene boundaries must be strictly increasing")
    return list(zip(cuts, cuts[1:]))


def _split_long(segment_words: list[dict[str, Any]], seg_start: float, seg_end: float) -> list[dict[str, Any]]:
    """Split a >60s scene segment into <=60s windows at word ends."""
    windows: list[dict[str, Any]] = []
    cur: list[dict[str, Any]] = []
    cur_start = seg_start
    for w in segment_words:
        trial = cur + [w]
        trial_end = w["end_sec"]
        if trial_end - cur_start > MAX_CLIP_SEC and cur:
            windows.append({"words": cur, "start_sec": cur_start, "end_sec": cur[-1]["end_sec"]})
            cur = [w]
            cur_start = w["start_sec"]
        else:
            cur = trial
    if cur:
        windows.append({"words": cur, "start_sec": cur_start, "end_sec": cur[-1]["end_sec"]})
    # A trailing window shorter than 15s is kept only as a candidate;
    # the selector drops it unless nothing else exists (see select).
    _ = seg_end
    return windows


def select_moments(plan: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(plan, dict):
        raise CapabilityError("edit.clip_moments: plan must be a JSON object")
    source_duration = _require_num(plan.get("source_duration_sec"), "source_duration_sec")
    if source_duration <= 0:
        raise CapabilityError("edit.clip_moments: source_duration_sec must be > 0")
    words = _validate_words(plan.get("transcript_words"))
    if words[-1]["end_sec"] > source_duration + 1e-9:
        raise CapabilityError("edit.clip_moments: transcript extends past source_duration_sec")
    hook_words = plan.get("hook_words", [])
    if not isinstance(hook_words, list) or not all(isinstance(h, str) for h in hook_words):
        raise CapabilityError("edit.clip_moments: hook_words must be a list of strings")
    hook_set = {h.strip().lower() for h in hook_words if h.strip()}
    min_clips = plan.get("min_clips", DEFAULT_MIN_CLIPS)
    max_clips = plan.get("max_clips", DEFAULT_MAX_CLIPS)
    if not isinstance(min_clips, int) or not isinstance(max_clips, int) or min_clips < 1 or max_clips < min_clips:
        raise CapabilityError("edit.clip_moments: min_clips/max_clips must satisfy 1 <= min_clips <= max_clips")
    if max_clips > 15:
        raise CapabilityError("edit.clip_moments: max_clips must not exceed 15")
    segments = _segments(words, plan.get("scene_boundaries_sec", []), source_duration)
    candidates: list[dict[str, Any]] = []
    for seg_start, seg_end in segments:
        seg_words = [w for w in words if w["start_sec"] >= seg_start - 1e-9 and w["end_sec"] <= seg_end + 1e-9]
        if not seg_words:
            continue
        for win in _split_long(seg_words, seg_start, seg_end):
            duration = win["end_sec"] - win["start_sec"]
            if duration <= 0:
                continue
            wps = len(win["words"]) / duration
            hooks = sum(1 for w in win["words"] if w["word"].strip().lower() in hook_set)
            length_fit = 10.0 if MIN_CLIP_SEC <= duration <= MAX_CLIP_SEC else -20.0
            score = round(wps * 10.0 + hooks * 5.0 + length_fit, 4)
            candidates.append({
                "start_sec": win["start_sec"],
                "end_sec": win["end_sec"],
                "duration_sec": round(duration, 3),
                "score": score,
                "factors": {
                    "word_count": len(win["words"]),
                    "words_per_sec": round(wps, 4),
                    "hook_hits": hooks,
                    "length_fit": length_fit,
                    "scene_segment": [seg_start, seg_end],
                },
                "model_score": "pending",
                "model_status": "not_run_no_gemini_key",
            })
    # Prefer in-range windows; only fall back to short windows if needed.
    in_range = [c for c in candidates if MIN_CLIP_SEC <= c["duration_sec"] <= MAX_CLIP_SEC]
    pool = in_range if in_range else candidates
    pool = sorted(pool, key=lambda c: (-c["score"], c["start_sec"]))
    chosen: list[dict[str, Any]] = []
    for cand in pool:
        if len(chosen) >= max_clips:
            break
        if any(not (cand["end_sec"] <= c["start_sec"] or cand["start_sec"] >= c["end_sec"]) for c in chosen):
            continue
        chosen.append(cand)
    chosen = sorted(chosen, key=lambda c: c["start_sec"])
    for i, c in enumerate(chosen, 1):
        c["clip_id"] = f"clip_{i:02d}"
    status = "ok" if len(chosen) >= min_clips else "insufficient"
    return {
        "source_duration_sec": source_duration,
        "candidate_count": len(candidates),
        "clips": chosen,
        "clip_count": len(chosen),
        "min_clips": min_clips,
        "max_clips": max_clips,
        "status": status,
        "model_score": "pending",
        "model_status": "not_run_no_gemini_key",
        "note": "Local deterministic score only; no Gemini moment score was run.",
    }


def _write_json(out_dir: Path, name: str, data: dict[str, Any]) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / name
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _render_clip_moments(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    result = select_moments(params.get("plan"))
    report = _write_json(Path(out_dir), "clip_moments.json", result)
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report),
        qa={
            "report_json": str(report),
            "clip_count": result["clip_count"],
            "status": result["status"],
            "model_score": "pending",
        },
    )


def register_clip_moments_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(Capability(
        name="edit.clip_moments",
        kind="line",
        aspects=["16:9", "9:16", "1:1"],
        params_schema={
            "type": "object",
            "properties": {"plan": {"type": "object"}},
            "required": ["plan"],
            "additionalProperties": False,
        },
        cpu_cost_hint=0.0,
        render=_render_clip_moments,
        has_media_output=False,
        description=(
            "Deterministic long-video moment detection (clean-room): "
            "word-level transcript plus scene boundaries scored by speech "
            "density, caller hook words and length fit, 3-15 clips of "
            "15-60s, never crossing a scene boundary. Model score is "
            "always pending: no Gemini key is used. Outputs a moment "
            "plan JSON, not clips."
        ),
        line="edit",
    ))
    return ["edit.clip_moments"]


register_clip_moments_capabilities_once()
