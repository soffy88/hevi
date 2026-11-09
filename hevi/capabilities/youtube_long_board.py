"""YouTube long-form board + draft plan (16:9, plan only).

Clean-room 16:9 counterpart of the 9:16 commentary-short line. The
short capabilities (``story.audio_first_board``,
``edit.jianying_draft_plan``) are NOT modified here: this module
adds two new capabilities for a 30-minute YouTube commentary long
video, so the short tests keep passing unchanged.

``story.youtube_long_board``: given planned sections (outline
summaries, not final narration), it validates that the sections
tile the total duration contiguously from 0, estimates the image
count at about 8 seconds per image (1800 seconds -> about 225
images; per-section ceiling estimates may sum a few higher, and
the report says so instead of forcing the sum), and derives
YouTube chapters from the five segment starts (first chapter at
0:00, as YouTube requires). Research fields left empty are
reported as ``research_pending``, never invented.

``edit.jianying_draft_long_plan``: a pyJianYingDraft-shaped draft
PLAN for 1920x1080, 30fps (video / narration / subtitle tracks),
with the same push-pull formula as the short plan
(amp = clamp(0.01 * shot duration, 0.05, 0.12), punch-in +0.04
within 0.5s, punch-out +0.02 in the last 0.3s). It outputs a plan
JSON only; ``draft_file`` is always null because the
pyJianYingDraft library is not importable in this environment
and nothing is pip-installed here to fake it. No media, no
audio, and no voice are produced.
"""

from __future__ import annotations

import importlib.util
import json
import math
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
_KEY_FIELDS = ("api_key", "apikey", "token", "secret", "password", "key")
_TOL = 0.5
_TOTAL_MIN = 1500.0
_TOTAL_MAX = 2100.0
_TARGET_TOTAL = 1800.0
_SECONDS_PER_IMAGE = 8.0
_WIDTH = 1920
_HEIGHT = 1080
_FPS = 30


def _is_num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _require_str(value: Any, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CapabilityError(f"youtube_long_board: {what} must be a non-empty string")
    return value.strip()


def _reject_keys(obj: Any, what: str) -> None:
    if isinstance(obj, dict):
        for field in _KEY_FIELDS:
            if field in obj:
                raise CapabilityError(
                    f"youtube_long_board: key-like fields are not accepted ({what})"
                )


def _fmt_chapter(seconds: float) -> str:
    total = int(round(seconds))
    return f"{total // 60}:{total % 60:02d}"


def estimate_shots(total_duration_sec: float) -> int:
    """Image estimate at about 8 seconds per image (1800s -> 225)."""
    if not _is_num(total_duration_sec) or float(total_duration_sec) <= 0:
        raise CapabilityError("youtube_long_board: total_duration_sec must be a positive number")
    return int(round(float(total_duration_sec) / _SECONDS_PER_IMAGE))


def build_long_board(board_input: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(board_input, dict):
        raise CapabilityError("story.youtube_long_board: board_input must be a JSON object")
    _reject_keys(board_input, "board_input")
    title = _require_str(board_input.get("title"), "title")
    total = board_input.get("total_duration_sec")
    if not _is_num(total):
        raise CapabilityError("story.youtube_long_board: total_duration_sec must be a number")
    total = float(total)
    if not (_TOTAL_MIN <= total <= _TOTAL_MAX):
        raise CapabilityError(
            f"story.youtube_long_board: total duration {total}s outside {_TOTAL_MIN}-{_TOTAL_MAX}s"
        )
    sections_raw = board_input.get("sections")
    if not isinstance(sections_raw, list) or not sections_raw:
        raise CapabilityError("story.youtube_long_board: sections must be a non-empty list")
    sections: list[dict[str, Any]] = []
    cursor = 0.0
    pending: list[str] = []
    for pos, sec in enumerate(sections_raw):
        if not isinstance(sec, dict):
            raise CapabilityError(f"story.youtube_long_board: section {pos} must be a JSON object")
        _reject_keys(sec, f"section {pos}")
        start = sec.get("start_sec")
        end = sec.get("end_sec")
        if not _is_num(start) or not _is_num(end):
            raise CapabilityError(f"story.youtube_long_board: section {pos} start_sec/end_sec must be numbers")
        start, end = float(start), float(end)
        if abs(start - cursor) > _TOL:
            raise CapabilityError(
                f"story.youtube_long_board: section {pos} starts at {start}s but previous "
                f"section ends at {cursor}s (sections must tile contiguously from 0)"
            )
        if end <= start:
            raise CapabilityError(f"story.youtube_long_board: section {pos} end_sec must exceed start_sec")
        summary = _require_str(sec.get("summary"), f"section {pos}.summary")
        duration = end - start
        shot_est = int(math.ceil(duration / _SECONDS_PER_IMAGE))
        research = sec.get("research_fields", {})
        if not isinstance(research, dict):
            raise CapabilityError(f"story.youtube_long_board: section {pos} research_fields must be an object")
        missing = [k for k, v in research.items() if v in (None, "", "pending", "research_pending")]
        for k in missing:
            pending.append(f"section {pos} research_pending: {k}")
        sections.append({
            "index": pos, "segment": sec.get("segment"),
            "title": sec.get("section_title"), "start_sec": start, "end_sec": end,
            "duration_sec": round(duration, 3), "summary": summary,
            "shot_estimate_ceil": shot_est, "research_fields": research,
            "research_pending_fields": missing,
        })
        cursor = end
    if abs(cursor - total) > _TOL:
        raise CapabilityError(
            f"story.youtube_long_board: sections end at {cursor}s but total_duration_sec "
            f"is {total}s"
        )
    segment_starts: dict[int, float] = {}
    for sec in sections:
        seg = sec.get("segment")
        if isinstance(seg, int) and seg not in segment_starts:
            segment_starts[seg] = sec["start_sec"]
    chapters = [
        {"start": _fmt_chapter(start), "start_sec": start,
         "title": f"第{seg}段"}
        for seg, start in sorted(segment_starts.items())
    ]
    if not chapters or chapters[0]["start_sec"] != 0.0:
        raise CapabilityError(
            "story.youtube_long_board: YouTube chapters require a chapter at 0:00 "
            "(first section must start at 0)"
        )
    shot_round = estimate_shots(total)
    shot_ceil_sum = sum(s["shot_estimate_ceil"] for s in sections)
    return {
        "capability": "story.youtube_long_board",
        "format_label": "解说长片",
        "disclaimer": "解说长片，不是演绎真片：画面为静帧 / 推拉 + 字幕，无真人表演视频。",
        "title": title,
        "aspect": "16:9", "width": _WIDTH, "height": _HEIGHT, "fps": _FPS,
        "total_duration_sec": total,
        "seconds_per_image": _SECONDS_PER_IMAGE,
        "shot_estimate_round": shot_round,
        "shot_estimate_per_section_ceil_sum": shot_ceil_sum,
        "shot_estimate_note": (
            f"About {shot_round} images at 8s per image for {total}s; per-section "
            f"ceiling estimates sum to {shot_ceil_sum} and may run a few higher. "
            "No images are generated here."
        ),
        "chapters": chapters,
        "sections": sections,
        "research_pending": pending,
        "srt_status": board_input.get("srt_status", "planned_not_measured"),
        "media_status": "plan_only_no_images_no_audio",
    }


def probe_jianying_library() -> dict[str, Any]:
    present = importlib.util.find_spec("pyJianYingDraft") is not None
    return {"library": "pyJianYingDraft", "importable": present,
            "status": "ready" if present else "not_importable_plan_only",
            "note": ("Library importable; a real draft file still requires a "
                     "separate production step.")
            if present else
            ("Library is not importable in this environment; only a plan "
             "JSON is produced and draft_file stays null. Nothing is "
             "pip-installed here to fake it.")}


def _push_amplitude(duration: float) -> float:
    return round(min(0.12, max(0.05, 0.01 * duration)), 4)


def build_long_draft_plan(plan_input: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(plan_input, dict):
        raise CapabilityError("edit.jianying_draft_long_plan: plan_input must be a JSON object")
    _reject_keys(plan_input, "plan_input")
    title = _require_str(plan_input.get("title"), "title")
    shots_raw = plan_input.get("shots")
    if not isinstance(shots_raw, list) or not shots_raw:
        raise CapabilityError("edit.jianying_draft_long_plan: shots must be a non-empty list")
    shots: list[dict[str, Any]] = []
    cursor = 0.0
    for pos, shot in enumerate(shots_raw):
        if not isinstance(shot, dict):
            raise CapabilityError(f"edit.jianying_draft_long_plan: shot {pos} must be a JSON object")
        _reject_keys(shot, f"shot {pos}")
        duration = shot.get("duration_sec")
        if not _is_num(duration) or float(duration) <= 0:
            raise CapabilityError(f"edit.jianying_draft_long_plan: shot {pos} duration_sec must be positive")
        duration = float(duration)
        start = shot.get("start_sec", cursor)
        if not _is_num(start) or abs(float(start) - cursor) > _TOL:
            raise CapabilityError(
                f"edit.jianying_draft_long_plan: shot {pos} must start at {cursor}s "
                "(shots must tile contiguously from 0)"
            )
        amp = _push_amplitude(duration)
        shots.append({
            "index": pos, "start_sec": float(start), "duration_sec": duration,
            "end_sec": round(float(start) + duration, 3),
            "push_pull": {"from": 1.0, "to": round(1.0 + amp, 4), "amplitude": amp},
            "punch_in": {"offset_sec": 0.0, "scale_delta": 0.04, "recover_within_sec": 0.5},
            "punch_out": {"offset_sec": round(duration - 0.3, 3) if duration >= 0.3 else 0.0,
                          "scale_delta": 0.02},
            "image": shot.get("image", "pending_no_image"),
            "caption": shot.get("caption"),
        })
        cursor = float(start) + duration
    total = round(cursor, 3)
    return {
        "capability": "edit.jianying_draft_long_plan",
        "format_label": "解说长片",
        "title": title,
        "aspect": "16:9", "width": _WIDTH, "height": _HEIGHT, "fps": _FPS,
        "tracks": ["video", "narration", "subtitle"],
        "total_duration_sec": total,
        "shot_count": len(shots),
        "shots": shots,
        "draft_file": None,
        "library_probe": probe_jianying_library(),
        "status": "plan_only_no_draft_file",
        "note": "Plan JSON only. No Jianying draft file is written here.",
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    _reject_keys(params, "params")
    if "board" in params:
        result = build_long_board(params["board"])
        name = "youtube_long_board.json"
    else:
        result = build_long_draft_plan(params["plan"])
        name = "jianying_draft_long_plan.json"
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    native = None
    if name == "jianying_draft_long_plan.json":
        shots = list(result.get("shots") or [])
        from hevi.studio.jianying_native import (
            NativeDraftUnavailable,
            items_from_shots,
            shots_have_media,
            write_native_draft,
        )

        if shots_have_media(shots):
            try:
                export = write_native_draft(
                    str(result.get("title") or "hevi_long_draft"),
                    items_from_shots([
                        {**s, "start_sec": s.get("start_sec", 0),
                         "end_sec": float(s.get("start_sec", 0)) + float(s.get("duration_sec", 0))}
                        for s in shots
                    ]),
                    out_dir / "native",
                    width=result.get("width") or 1920,
                    height=result.get("height") or 1080,
                    fps=result.get("fps") or 30,
                )
                native = export.as_dict()
                result["draft_file"] = export.draft_zip or export.draft_dir
                result["status"] = "native_draft_written"
                result["note"] = "Real JianYing Pro draft written with pyJianYingDraft."
            except NativeDraftUnavailable as exc:
                result["native_error"] = str(exc)
    report = out_dir / name
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0, sha256=compute_sha256(report),
        qa={"report_json": str(report), "format_label": "解说长片",
            "native": native is not None,
            "draft_zip": (native or {}).get("draft_zip")},
    )


def register_youtube_long_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(Capability(
        name="story.youtube_long_board",
        kind="line", aspects=["16:9"],
        params_schema={
            "type": "object",
            "properties": {"board": {"type": "object"}},
            "required": ["board"], "additionalProperties": False,
        },
        cpu_cost_hint=0.0, render=_render, has_media_output=False,
        description=(
            "YouTube long-form board (clean-room, plan only): validates that "
            "planned sections tile 1500-2100s contiguously from 0, estimates "
            "images at about 8s per image, derives YouTube chapters from "
            "segment starts, and reports empty research fields as "
            "research_pending instead of inventing them. No media rendered."
        ),
        line="story",
    ))
    register(Capability(
        name="edit.jianying_draft_long_plan",
        kind="line", aspects=["16:9"],
        params_schema={
            "type": "object",
            "properties": {"plan": {"type": "object"}},
            "required": ["plan"], "additionalProperties": False,
        },
        cpu_cost_hint=0.0, render=_render, has_media_output=False,
        description=(
            "YouTube long-form Jianying draft PLAN (clean-room, plan only): "
            "1920x1080, 30fps, video / narration / subtitle tracks, push-pull "
            "and punch keyframe parameters. Outputs a plan JSON; draft_file "
            "stays null because the library is not importable here."
        ),
        line="edit",
    ))
    return ["story.youtube_long_board", "edit.jianying_draft_long_plan"]


register_youtube_long_capabilities_once()
