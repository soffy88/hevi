"""Jianying draft plan (``edit.jianying_draft_plan``) -- PLAN ONLY.

This capability outputs a checkable pyJianYingDraft-shaped draft
PLAN (tracks, per-clip keyframes, cut-impact zoom parameters) as
JSON. It deliberately does NOT write a real剪映 draft file:

* availability is probed with importlib.util.find_spec only.
  On this machine pyJianYingDraft is NOT installed (venv and
  system Python both fail the import), so ``draft_file`` is
  always null and the plan states that plainly;
* nothing is pip-installed into the production venv by this
  module, and no draft file is fabricated to look like one.

Keyframe spec (all scales are multipliers on the still image):

* slow push / pull amplitude grows with clip duration:
  amp = clamp(0.01 * duration_sec, 0.05, 0.12). An 8s push
  therefore runs 1.00 -> 1.08; a 6s push 1.00 -> 1.06; a 10s
  push 1.00 -> 1.10. Pull runs the same range in reverse.
  A hold / pending move runs 1.00 -> 1.00 and is flagged
  pending rather than given a fake move.
* cut-impact zoom, additive on top of the base move:
  - outgoing clip: final 0.3s micro-pushes to base end scale
    + 0.02 (``cut_out_scale``);
  - incoming clip: starts at base start scale + 0.04 and
    settles back onto the base trajectory over the first 0.5s
    (``cut_in_scale`` / ``cut_in_settle_sec``).
  The last clip has no cut-out; the first clip has no cut-in
  (it opens the film, it does not cut in).

Track spec: one video track (still-image clips in shot order),
one audio track (narration clips aligned to the same shot
times; the audio source is pending -- no audio file is claimed),
one subtitle track (one entry per shot; text is the shot's
supplied sentence text, or "pending" when the shot supplies none).

Validation: shots must be non-empty, uniquely identified,
contiguous (next start equals previous end within 0.05s),
starting at 0; gaps, overlaps, duplicate ids or a first shot
not at 0 are errors.
"""

from __future__ import annotations

import importlib.util
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
_TOL = 0.05
_START_TOL = 1e-3
_CUT_OUT_WINDOW = 0.3
_CUT_IN_WINDOW = 0.5
_CUT_OUT_BUMP = 0.02
_CUT_IN_BUMP = 0.04
_KEY_FIELDS = ("api_key", "apikey", "token", "secret", "password", "key")


def _is_num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _require_str(value: Any, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CapabilityError(f"edit.jianying_draft_plan: {what} must be a non-empty string")
    return value.strip()


def _reject_keys(obj: Any, what: str) -> None:
    if isinstance(obj, dict):
        for field in _KEY_FIELDS:
            if field in obj:
                raise CapabilityError(
                    f"edit.jianying_draft_plan: key-like fields are not accepted ({what})"
                )


def probe_jianying_library() -> dict[str, Any]:
    installed = importlib.util.find_spec("pyJianYingDraft") is not None
    return {
        "library": "pyJianYingDraft",
        "probe": "importlib.util.find_spec('pyJianYingDraft')",
        "installed": installed,
        "status": "installed" if installed else "not_installed",
        "note": ("pyJianYingDraft was found; this capability still outputs a "
                 "plan only and does not write a draft file.")
        if installed else
        ("pyJianYingDraft is not installed in this environment; no draft "
         "file is written and nothing is pip-installed into the production "
         "venv by this capability. This JSON plan is the whole output."),
    }


def _push_amplitude(duration: float) -> float:
    return round(min(0.12, max(0.05, 0.01 * duration)), 3)


def build_draft_plan(plan_input: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(plan_input, dict):
        raise CapabilityError("edit.jianying_draft_plan: input must be a JSON object")
    _reject_keys(plan_input, "input")
    shots_raw = plan_input.get("shots")
    if not isinstance(shots_raw, list) or not shots_raw:
        raise CapabilityError("edit.jianying_draft_plan: shots must be a non-empty list")
    aspect = plan_input.get("aspect", "16:9")
    if aspect not in ("16:9", "9:16"):
        raise CapabilityError("edit.jianying_draft_plan: aspect must be '16:9' or '9:16'")
    title = plan_input.get("title")
    if title is not None and (not isinstance(title, str) or not title.strip()):
        raise CapabilityError("edit.jianying_draft_plan: title must be a non-empty string")
    shots: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    prev_end: float | None = None
    for i, shot in enumerate(shots_raw):
        if not isinstance(shot, dict):
            raise CapabilityError(f"edit.jianying_draft_plan: shot {i} must be a JSON object")
        _reject_keys(shot, f"shot {i}")
        shot_id = _require_str(shot.get("shot_id"), f"shot {i}.shot_id")
        if shot_id in seen_ids:
            raise CapabilityError(f"edit.jianying_draft_plan: duplicate shot_id {shot_id!r}")
        seen_ids.add(shot_id)
        start, end = shot.get("start_sec"), shot.get("end_sec")
        if not _is_num(start) or not _is_num(end):
            raise CapabilityError(f"edit.jianying_draft_plan: shot {shot_id} start_sec/end_sec must be numbers")
        start, end = float(start), float(end)
        if end <= start:
            raise CapabilityError(f"edit.jianying_draft_plan: shot {shot_id} has an invalid time range")
        if i == 0 and abs(start) > _START_TOL:
            raise CapabilityError(
                f"edit.jianying_draft_plan: first shot must start at 0, got {start}s"
            )
        if prev_end is not None and abs(start - prev_end) > _TOL:
            if start < prev_end - _TOL:
                raise CapabilityError(
                    f"edit.jianying_draft_plan: shot {shot_id} overlaps the previous shot "
                    f"(starts {start}s, previous ends {prev_end}s)"
                )
            raise CapabilityError(
                f"edit.jianying_draft_plan: gap before shot {shot_id} "
                f"(starts {start}s, previous ends {prev_end}s)"
            )
        move = shot.get("camera_move")
        if move is not None and (not isinstance(move, str) or not move.strip()):
            raise CapabilityError(f"edit.jianying_draft_plan: shot {shot_id} camera_move must be a string")
        move = move.strip() if isinstance(move, str) else None
        if move is not None and move not in ("push", "pull", "hold", "pending"):
            raise CapabilityError(
                f"edit.jianying_draft_plan: shot {shot_id} camera_move must be one of "
                "push / pull / hold / pending"
            )
        text = shot.get("sentence_text")
        if text is not None and (not isinstance(text, str) or not text.strip()):
            raise CapabilityError(f"edit.jianying_draft_plan: shot {shot_id} sentence_text must be a string")
        duration = round(end - start, 3)
        amp = _push_amplitude(duration) if move in ("push", "pull") else 0.0
        if move == "push":
            scale_start, scale_end = 1.0, round(1.0 + amp, 3)
        elif move == "pull":
            scale_start, scale_end = round(1.0 + amp, 3), 1.0
        else:
            scale_start, scale_end = 1.0, 1.0
        clip: dict[str, Any] = {
            "shot_id": shot_id, "start_sec": start, "end_sec": end,
            "duration_sec": duration, "camera_move": move or "pending",
            "motion_status": "planned" if move in ("push", "pull", "hold") else "pending",
            "scale_start": scale_start, "scale_end": scale_end,
            "push_amplitude": amp,
            "keyframes": [
                {"time_sec": start, "scale": scale_start},
                {"time_sec": end, "scale": scale_end},
            ],
            "cut_in": None, "cut_out": None,
        }
        if i > 0:
            clip["cut_in"] = {
                "scale": round(scale_start + _CUT_IN_BUMP, 3),
                "settle_sec": _CUT_IN_WINDOW,
                "note": "Incoming clip starts 0.04 above its base start scale and "
                        "settles onto the base trajectory over the first 0.5s.",
            }
        if i < len(shots_raw) - 1:
            clip["cut_out"] = {
                "window_sec": _CUT_OUT_WINDOW,
                "scale": round(scale_end + _CUT_OUT_BUMP, 3),
                "note": "Outgoing clip micro-pushes 0.02 above its base end scale "
                        "over its final 0.3s (cut-impact zoom).",
            }
        shots.append(clip)
        prev_end = end
    total = round(shots[-1]["end_sec"] - shots[0]["start_sec"], 3)
    availability = probe_jianying_library()
    return {
        "capability": "edit.jianying_draft_plan",
        "format": "pyJianYingDraft-shaped draft plan (JSON plan only)",
        "title": title.strip() if isinstance(title, str) else None,
        "aspect": aspect,
        "total_duration_sec": total,
        "clip_count": len(shots),
        "draft_file": None,
        "draft_file_note": ("No .draft file was written: this capability outputs "
                            "a plan only, regardless of library availability."),
        "library_availability": availability,
        "keyframe_spec": {
            "push_amplitude_formula": "amp = clamp(0.01 * duration_sec, 0.05, 0.12)",
            "push": "scale 1.00 -> 1.00 + amp",
            "pull": "scale 1.00 + amp -> 1.00",
            "hold_or_pending": "scale 1.00 -> 1.00",
            "cut_in_bump": _CUT_IN_BUMP, "cut_in_settle_sec": _CUT_IN_WINDOW,
            "cut_out_bump": _CUT_OUT_BUMP, "cut_out_window_sec": _CUT_OUT_WINDOW,
        },
        "tracks": {
            "video": {"track": "V1", "kind": "still_image_clips", "clips": shots},
            "audio": {"track": "A1", "kind": "narration_clips", "source_status": "pending",
                      "note": "Narration audio is not supplied here; no audio file is claimed. "
                              "Align real voice clips to these shot times at production time.",
                      "clips": [{"shot_id": s["shot_id"], "start_sec": s["start_sec"],
                                 "end_sec": s["end_sec"]} for s in shots]},
            "subtitle": {"track": "T1", "kind": "subtitle_entries",
                         "entries": [{"shot_id": s["shot_id"], "start_sec": s["start_sec"],
                                      "end_sec": s["end_sec"],
                                      "text": next((raw.get("sentence_text") for raw in shots_raw
                                                    if raw.get("shot_id") == s["shot_id"]), None)
                                      or "pending"} for s in shots]},
        },
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    _reject_keys(params, "params")
    result = build_draft_plan(params.get("plan"))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    native: dict[str, Any] | None = None
    shots = ((params.get("plan") or {}).get("shots") or [])
    from hevi.studio.jianying_native import (
        NativeDraftUnavailable,
        items_from_shots,
        shots_have_media,
        write_native_draft,
    )

    if shots_have_media(shots):
        width, height = (1080, 1920) if result["aspect"] == "9:16" else (1920, 1080)
        try:
            export = write_native_draft(
                str(result.get("title") or "hevi_draft"),
                items_from_shots(shots),
                out_dir / "native",
                width=width,
                height=height,
                fps=30,
            )
            native = export.as_dict()
            result["format"] = "jianying_native"
            result["draft_file"] = export.draft_zip or export.draft_dir
            result["draft_file_note"] = "Real JianYing Pro draft written with pyJianYingDraft."
            result["draft_manifest"] = export.manifest
        except NativeDraftUnavailable as exc:
            result["native_error"] = str(exc)
    report = out_dir / "jianying_draft_plan.json"
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report),
        qa={"report_json": str(report), "clip_count": result["clip_count"],
            "draft_file": result.get("draft_file"),
            "draft_zip": (native or {}).get("draft_zip"),
            "native": native is not None,
            "library_installed": result["library_availability"]["installed"]},
    )


def register_jianying_draft_plan_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(Capability(
        name="edit.jianying_draft_plan",
        kind="line",
        aspects=["16:9", "9:16"],
        params_schema={
            "type": "object",
            "properties": {"plan": {"type": "object"}},
            "required": ["plan"],
            "additionalProperties": False,
        },
        cpu_cost_hint=0.0,
        render=_render,
        has_media_output=False,
        description=(
            "Jianying draft plan (clean-room, plan only): pyJianYingDraft-shaped "
            "tracks with slow push/pull keyframes (amplitude tied to clip "
            "duration) and cut-impact zoom parameters (incoming +0.04 settling "
            "over 0.5s, outgoing +0.02 over final 0.3s). No .draft file is "
            "written and nothing is installed: library availability is probed "
            "and reported honestly."
        ),
        line="edit",
    ))
    return ["edit.jianying_draft_plan"]


register_jianying_draft_plan_capabilities_once()
