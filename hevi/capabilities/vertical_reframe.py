"""9:16 intelligent reframe planning (``edit.vertical_reframe``).

Clean-room method intake: from a clip window, speaker speech
intervals and face tracks, choose one of four layouts and emit the
crop / pane parameters a renderer can consume. No video is
rendered here.

Layouts, with the gate that decides each one:
* TRACK: exactly one speaker is speaking in the window. The crop
  follows that speaker's face centre.
* GENERAL: nobody is speaking (or no face track is supplied).
  Centre crop, blurred-background flag set for the renderer.
* SPLIT: two speakers genuinely take turns. Gate: both speakers
  speak at least 5 seconds in the window, each takes at least 2
  turns, and neither is silent for the whole window. A single
  speaker who is silent for 30 seconds or more in the window
  never triggers SPLIT; that case falls back to TRACK/GENERAL.
* SCREENCAST: the caller flags screen_share and a speaker is
  present. The screen is the main area and the speaker is a
  picture-in-picture box; without a speaker, screen_share alone
  falls back to GENERAL with a note, it does not invent a speaker.

Coordinates are normalised 0-1 in source space. The 9:16 crop
width is derived from the source aspect (crop_height = 1.0 in
source-height units, crop_width = (source_height * 9 / 16) /
source_width), never from a guessed pixel size. Subtitle seam
for SPLIT is the horizontal seam between the two panes.

Failure contract: out-of-range face boxes, unsorted or negative
intervals, duplicate speaker ids, unknown layout flags and a
window outside the source all raise CapabilityError.
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


def _is_num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _require_num(value: Any, what: str) -> float:
    if not _is_num(value):
        raise CapabilityError(f"edit.vertical_reframe: {what} must be a number")
    return float(value)


def _require_str(value: Any, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CapabilityError(f"edit.vertical_reframe: {what} must be a non-empty string")
    return value.strip()


def _intervals(speaker: dict[str, Any], sid: str) -> list[tuple[float, float]]:
    raw = speaker.get("speaking_intervals", [])
    if not isinstance(raw, list):
        raise CapabilityError(f"edit.vertical_reframe: speaker {sid} speaking_intervals must be a list")
    out: list[tuple[float, float]] = []
    prev_end = -1.0
    for iv in raw:
        if not isinstance(iv, (list, tuple)) or len(iv) != 2:
            raise CapabilityError(f"edit.vertical_reframe: speaker {sid} interval must be [start, end]")
        s, e = _require_num(iv[0], f"speaker {sid} interval start"), _require_num(iv[1], f"speaker {sid} interval end")
        if s < 0 or e <= s or s < prev_end - 1e-9:
            raise CapabilityError(f"edit.vertical_reframe: speaker {sid} has an invalid or unsorted interval")
        prev_end = e
        out.append((s, e))
    return out


def _speaking_in_window(intervals: list[tuple[float, float]], start: float, end: float) -> float:
    total = 0.0
    for s, e in intervals:
        total += max(0.0, min(e, end) - max(s, start))
    return total


def _face_centre(tracks: list[dict[str, Any]], sid: str, start: float, end: float) -> tuple[float, float] | None:
    xs: list[float] = []
    ys: list[float] = []
    for t in tracks:
        if t.get("speaker_id") != sid:
            continue
        ts, te = t["start_sec"], t["end_sec"]
        if te <= start or ts >= end:
            continue
        xs.append(t["x"] + t["w"] / 2.0)
        ys.append(t["y"] + t["h"] / 2.0)
    if not xs:
        return None
    return sum(xs) / len(xs), sum(ys) / len(ys)


def plan_reframe(plan: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(plan, dict):
        raise CapabilityError("edit.vertical_reframe: plan must be a JSON object")
    src_w = _require_num(plan.get("source_width"), "source_width")
    src_h = _require_num(plan.get("source_height"), "source_height")
    if src_w <= 0 or src_h <= 0:
        raise CapabilityError("edit.vertical_reframe: source dimensions must be > 0")
    win = plan.get("window")
    if not isinstance(win, dict):
        raise CapabilityError("edit.vertical_reframe: window must be a JSON object")
    start = _require_num(win.get("start_sec"), "window.start_sec")
    end = _require_num(win.get("end_sec"), "window.end_sec")
    if start < 0 or end <= start:
        raise CapabilityError("edit.vertical_reframe: window must satisfy 0 <= start < end")
    speakers_raw = plan.get("speakers", [])
    if not isinstance(speakers_raw, list):
        raise CapabilityError("edit.vertical_reframe: speakers must be a list")
    speakers: dict[str, dict[str, Any]] = {}
    for sp in speakers_raw:
        if not isinstance(sp, dict):
            raise CapabilityError("edit.vertical_reframe: each speaker must be a JSON object")
        sid = _require_str(sp.get("id"), "speaker.id")
        if sid in speakers:
            raise CapabilityError(f"edit.vertical_reframe: duplicate speaker id {sid}")
        speakers[sid] = {"intervals": _intervals(sp, sid)}
    tracks_raw = plan.get("face_tracks", [])
    if not isinstance(tracks_raw, list):
        raise CapabilityError("edit.vertical_reframe: face_tracks must be a list")
    tracks: list[dict[str, Any]] = []
    for t in tracks_raw:
        if not isinstance(t, dict):
            raise CapabilityError("edit.vertical_reframe: each face track must be a JSON object")
        sid = _require_str(t.get("speaker_id"), "face_track.speaker_id")
        if sid not in speakers:
            raise CapabilityError(f"edit.vertical_reframe: face track for unknown speaker {sid}")
        x = _require_num(t.get("x"), "face_track.x")
        y = _require_num(t.get("y"), "face_track.y")
        w = _require_num(t.get("w"), "face_track.w")
        h = _require_num(t.get("h"), "face_track.h")
        ts = _require_num(t.get("start_sec"), "face_track.start_sec")
        te = _require_num(t.get("end_sec"), "face_track.end_sec")
        if not (0 <= x <= 1 and 0 <= y <= 1 and 0 < w <= 1 and 0 < h <= 1 and x + w <= 1 + 1e-9 and y + h <= 1 + 1e-9):
            raise CapabilityError("edit.vertical_reframe: face box must lie inside normalised 0-1 source space")
        if ts < 0 or te <= ts:
            raise CapabilityError("edit.vertical_reframe: face track has an invalid time range")
        tracks.append({"speaker_id": sid, "x": x, "y": y, "w": w, "h": h, "start_sec": ts, "end_sec": te})
    speaking = {sid: _speaking_in_window(v["intervals"], start, end) for sid, v in speakers.items()}
    active = [sid for sid, sec in speaking.items() if sec > 0]
    crop_w = min(1.0, (src_h * 9.0 / 16.0) / src_w)
    screen_share = bool(plan.get("screen_share", False))
    duration = end - start
    # SPLIT gate: two speakers, each >=5s, each >=2 turns in window, neither silent whole window.
    turns: dict[str, int] = {}
    for sid, v in speakers.items():
        turns[sid] = sum(1 for s, e in v["intervals"] if e > start and s < end)
    split_ok = (
        len(active) == 2
        and all(speaking[sid] >= 5.0 for sid in active)
        and all(turns[sid] >= 2 for sid in active)
        and not any(duration >= 30.0 and speaking[sid] == 0.0 for sid in speakers)
    )
    # A speaker silent for the whole window can never be a SPLIT pane.
    if len(speakers) == 2 and any(speaking[sid] == 0.0 for sid in speakers):
        split_ok = False
    if screen_share and active:
        sid = sorted(active, key=lambda s: -speaking[s])[0]
        centre = _face_centre(tracks, sid, start, end) or (0.5, 0.5)
        layout, reason = "SCREENCAST", "screen_share flagged and a speaker is present"
        crop = {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}
        pip = {"speaker_id": sid, "x": 0.70, "y": 0.70, "w": 0.28, "h": 0.28, "face_centre": list(centre)}
        panes = None
    elif split_ok:
        layout, reason = "SPLIT", "two speakers take turns in the window (SPLIT gate passed)"
        panes = []
        for i, sid in enumerate(sorted(active)):
            panes.append({
                "speaker_id": sid,
                "y_range": [i * 0.5, (i + 1) * 0.5],
                "crop": {"x": 0.0, "y": i * 0.5, "w": 1.0, "h": 0.5},
                "speaking_sec": round(speaking[sid], 3),
            })
        crop = {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}
        pip = None
    elif len(active) == 1:
        sid = active[0]
        centre = _face_centre(tracks, sid, start, end)
        cx = centre[0] if centre else 0.5
        x = min(max(cx - crop_w / 2.0, 0.0), 1.0 - crop_w) if crop_w < 1.0 else 0.0
        layout, reason = "TRACK", "exactly one speaker is speaking in the window"
        crop = {"x": round(x, 4), "y": 0.0, "w": round(crop_w, 4), "h": 1.0}
        pip = None
        panes = None
    else:
        layout, reason = "GENERAL", "no speaker is speaking in the window (or no face track)"
        crop = {"x": round((1.0 - crop_w) / 2.0, 4) if crop_w < 1.0 else 0.0, "y": 0.0, "w": round(crop_w, 4), "h": 1.0}
        pip = None
        panes = None
    return {
        "window": {"start_sec": start, "end_sec": end, "duration_sec": round(duration, 3)},
        "layout": layout,
        "reason": reason,
        "crop": crop,
        "pip": pip,
        "panes": panes,
        "subtitle_seam": "horizontal seam at y=0.5 between SPLIT panes" if layout == "SPLIT" else None,
        "blurred_background": layout == "GENERAL",
        "speaking_sec": {sid: round(sec, 3) for sid, sec in speaking.items()},
        "gate_checks": {
            "split_gate_passed": bool(split_ok),
            "turns_in_window": turns,
            "screen_share": screen_share,
        },
        "video_render": "pending",
        "note": "Reframe plan only; no video is rendered by this capability.",
    }


def _render_reframe(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    result = plan_reframe(params.get("plan"))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = out_dir / "vertical_reframe.json"
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report),
        qa={"report_json": str(report), "layout": result["layout"], "video_render": "pending"},
    )


def register_vertical_reframe_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(Capability(
        name="edit.vertical_reframe",
        kind="line",
        aspects=["9:16", "16:9"],
        params_schema={
            "type": "object",
            "properties": {"plan": {"type": "object"}},
            "required": ["plan"],
            "additionalProperties": False,
        },
        cpu_cost_hint=0.0,
        render=_render_reframe,
        has_media_output=False,
        description=(
            "9:16 reframe planning (clean-room): TRACK / GENERAL / SPLIT / "
            "SCREENCAST with an active-speaker gate for SPLIT (two speakers "
            "taking turns; a silent speaker never triggers SPLIT). Outputs "
            "crop and pane parameters; renders no video."
        ),
        line="edit",
    ))
    return ["edit.vertical_reframe"]


register_vertical_reframe_capabilities_once()
