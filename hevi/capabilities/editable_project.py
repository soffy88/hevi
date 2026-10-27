"""Editable project spec (``edit.editable_project``).

Clean-room method intake, written from the method description only.
It is deliberately not a copy of any desktop editor: no Electron,
no desktop shell, no playback engine. What it borrows is only the
shape -- a project an agent can read, write and re-edit -- which
hevi's existing ``edit.timeline_register`` does not provide (that
capability only registers generated clips onto a timeline).

Shape:
* Project: id, title, fps, duration, resolution, tracks.
* Track: id, kind (video, audio, text, image), clips in timeline
  order. Clip ids are unique across the whole project, so an edit
  can address any clip without ambiguity.
* Clip: source reference, timeline window, optional source window,
  and an edits map of re-editable fields (speed, volume, opacity,
  text). Unknown edit keys raise; nothing is silently ignored.
* Re-edits: rename, retime, move to another track of the same
  kind, set text, set speed, and split at a time. Every applied
  edit is appended to ``edit_history`` with a sequence number and
  returns a new project object; the input project is never mutated.

Validation, on every build and every edit: clips inside one track
must be sorted by timeline start and non-overlapping, every window
must lie inside the project duration with end > start, source
windows (when present) must have end > start, and split points
must lie strictly inside the clip.

Failure contract: any of the above violations, a duplicate id,
an unknown kind or action, a move across kinds, or an edit that
would break the timeline raises CapabilityError and leaves the
project unchanged.
"""

from __future__ import annotations

import copy
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
_TRACK_KINDS = ("video", "audio", "text", "image")
_EDIT_KEYS = ("speed", "volume", "opacity", "text")


def _is_num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _require_str(value: Any, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CapabilityError(f"edit.editable_project: {what} must be a non-empty string")
    return value.strip()


def _require_num(value: Any, what: str) -> float:
    if not _is_num(value):
        raise CapabilityError(f"edit.editable_project: {what} must be a number")
    return float(value)


def _clean_edits(edits: Any, what: str) -> dict[str, Any]:
    if edits is None:
        return {}
    if not isinstance(edits, dict):
        raise CapabilityError(f"edit.editable_project: {what} edits must be a JSON object")
    out: dict[str, Any] = {}
    for key, val in edits.items():
        if key not in _EDIT_KEYS:
            raise CapabilityError(f"edit.editable_project: {what} unknown edit field {key!r}")
        if key == "text":
            if not isinstance(val, str):
                raise CapabilityError(f"edit.editable_project: {what} edit text must be a string")
            out[key] = val
        else:
            val = _require_num(val, f"{what} edit {key}")
            if key == "speed" and val <= 0:
                raise CapabilityError(f"edit.editable_project: {what} edit speed must be > 0")
            if key == "volume" and not (0.0 <= val <= 2.0):
                raise CapabilityError(f"edit.editable_project: {what} edit volume must be between 0 and 2")
            if key == "opacity" and not (0.0 <= val <= 1.0):
                raise CapabilityError(f"edit.editable_project: {what} edit opacity must be between 0 and 1")
            out[key] = val
    return out


def _clean_clip(clip: Any, duration: float, what: str) -> dict[str, Any]:
    if not isinstance(clip, dict):
        raise CapabilityError(f"edit.editable_project: {what} must be a JSON object")
    cid = _require_str(clip.get("clip_id"), f"{what}.clip_id")
    source_ref = clip.get("source_ref")
    if source_ref is not None and not isinstance(source_ref, str):
        raise CapabilityError(f"edit.editable_project: {what} source_ref must be a string")
    start = _require_num(clip.get("timeline_start_sec"), f"{what}.timeline_start_sec")
    end = _require_num(clip.get("timeline_end_sec"), f"{what}.timeline_end_sec")
    if start < 0 or end > duration or end <= start:
        raise CapabilityError(f"edit.editable_project: {what} timeline window must lie inside the project duration with end > start")
    out: dict[str, Any] = {
        "clip_id": cid, "source_ref": source_ref,
        "timeline_start_sec": start, "timeline_end_sec": end,
        "edits": _clean_edits(clip.get("edits"), what),
    }
    for key in ("source_start_sec", "source_end_sec"):
        if clip.get(key) is not None:
            out[key] = _require_num(clip.get(key), f"{what}.{key}")
    if "source_start_sec" in out and "source_end_sec" in out and out["source_end_sec"] <= out["source_start_sec"]:
        raise CapabilityError(f"edit.editable_project: {what} source window must have end > start")
    return out


def _validate_project(project: dict[str, Any]) -> None:
    duration = project["duration_sec"]
    seen_clips: set[str] = set()
    for track in project["tracks"]:
        prev_end: float | None = None
        prev_start: float | None = None
        for clip in track["clips"]:
            if clip["clip_id"] in seen_clips:
                raise CapabilityError(f"edit.editable_project: duplicate clip id {clip['clip_id']!r}")
            seen_clips.add(clip["clip_id"])
            if prev_start is not None and clip["timeline_start_sec"] < prev_start:
                raise CapabilityError(f"edit.editable_project: track {track['track_id']!r} clips must be sorted by timeline start")
            if prev_end is not None and clip["timeline_start_sec"] < prev_end - 1e-9:
                raise CapabilityError(f"edit.editable_project: track {track['track_id']!r} clips overlap")
            prev_start, prev_end = clip["timeline_start_sec"], clip["timeline_end_sec"]
            if clip["timeline_end_sec"] > duration or clip["timeline_start_sec"] < 0:
                raise CapabilityError(f"edit.editable_project: clip {clip['clip_id']!r} lies outside the project duration")


def build_project(spec: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(spec, dict):
        raise CapabilityError("edit.editable_project: spec must be a JSON object")
    pid = _require_str(spec.get("project_id"), "project_id")
    title = _require_str(spec.get("title"), "title")
    fps = spec.get("fps")
    if not isinstance(fps, int) or isinstance(fps, bool) or fps < 1 or fps > 120:
        raise CapabilityError("edit.editable_project: fps must be an integer between 1 and 120")
    duration = _require_num(spec.get("duration_sec"), "duration_sec")
    if duration <= 0:
        raise CapabilityError("edit.editable_project: duration_sec must be > 0")
    resolution = spec.get("resolution", {})
    if not isinstance(resolution, dict):
        raise CapabilityError("edit.editable_project: resolution must be a JSON object")
    width, height = resolution.get("width"), resolution.get("height")
    if width is not None and (not _is_num(width) or width <= 0):
        raise CapabilityError("edit.editable_project: resolution.width must be > 0")
    if height is not None and (not _is_num(height) or height <= 0):
        raise CapabilityError("edit.editable_project: resolution.height must be > 0")
    tracks_raw = spec.get("tracks")
    if not isinstance(tracks_raw, list) or not tracks_raw:
        raise CapabilityError("edit.editable_project: tracks must be a non-empty list")
    tracks: list[dict[str, Any]] = []
    seen_tracks: set[str] = set()
    for i, tr in enumerate(tracks_raw):
        if not isinstance(tr, dict):
            raise CapabilityError(f"edit.editable_project: track {i} must be a JSON object")
        tid = _require_str(tr.get("track_id"), f"track {i}.track_id")
        if tid in seen_tracks:
            raise CapabilityError(f"edit.editable_project: duplicate track id {tid!r}")
        seen_tracks.add(tid)
        kind = tr.get("kind")
        if kind not in _TRACK_KINDS:
            raise CapabilityError(f"edit.editable_project: track {tid!r} unknown kind {kind!r}")
        clips_raw = tr.get("clips", [])
        if not isinstance(clips_raw, list):
            raise CapabilityError(f"edit.editable_project: track {tid!r} clips must be a list")
        clips = [_clean_clip(c, duration, f"track {tid!r} clip") for c in clips_raw]
        tracks.append({"track_id": tid, "kind": kind, "clips": clips})
    project = {
        "project_id": pid, "title": title, "fps": fps, "duration_sec": duration,
        "resolution": {"width": width, "height": height},
        "tracks": tracks, "edit_history": [],
    }
    _validate_project(project)
    clip_count = sum(len(t["clips"]) for t in tracks)
    return {**project, "summary": {"track_count": len(tracks), "clip_count": clip_count}}


def _find_clip(project: dict[str, Any], clip_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    for track in project["tracks"]:
        for clip in track["clips"]:
            if clip["clip_id"] == clip_id:
                return track, clip
    raise CapabilityError(f"edit.editable_project: unknown clip id {clip_id!r}")


def apply_edit(project: dict[str, Any], edit: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(project, dict) or not isinstance(project.get("tracks"), list):
        raise CapabilityError("edit.editable_project: project must be a built editable project")
    if not isinstance(edit, dict):
        raise CapabilityError("edit.editable_project: edit must be a JSON object")
    action = edit.get("action")
    out = copy.deepcopy(project)
    out.pop("summary", None)
    seq = len(out.get("edit_history", [])) + 1
    if action == "rename_clip":
        _, clip = _find_clip(out, _require_str(edit.get("clip_id"), "edit.clip_id"))
        new_id = _require_str(edit.get("new_clip_id"), "edit.new_clip_id")
        try:
            _find_clip(out, new_id)
        except CapabilityError:
            pass
        else:
            raise CapabilityError(f"edit.editable_project: new clip id {new_id!r} already exists")
        clip["clip_id"] = new_id
    elif action == "retime_clip":
        _, clip = _find_clip(out, _require_str(edit.get("clip_id"), "edit.clip_id"))
        clip["timeline_start_sec"] = _require_num(edit.get("timeline_start_sec"), "edit.timeline_start_sec")
        clip["timeline_end_sec"] = _require_num(edit.get("timeline_end_sec"), "edit.timeline_end_sec")
        if clip["timeline_end_sec"] <= clip["timeline_start_sec"]:
            raise CapabilityError("edit.editable_project: retimed clip must have end > start")
    elif action == "move_clip":
        src_track, clip = _find_clip(out, _require_str(edit.get("clip_id"), "edit.clip_id"))
        target_id = _require_str(edit.get("target_track_id"), "edit.target_track_id")
        target = None
        for tr in out["tracks"]:
            if tr["track_id"] == target_id:
                target = tr
        if target is None:
            raise CapabilityError(f"edit.editable_project: unknown target track {target_id!r}")
        if target["kind"] != src_track["kind"]:
            raise CapabilityError("edit.editable_project: move_clip only works between tracks of the same kind")
        src_track["clips"] = [c for c in src_track["clips"] if c is not clip]
        target["clips"].append(clip)
        target["clips"].sort(key=lambda c: c["timeline_start_sec"])
    elif action == "set_clip_text":
        _, clip = _find_clip(out, _require_str(edit.get("clip_id"), "edit.clip_id"))
        clip["edits"]["text"] = _require_str(edit.get("text"), "edit.text")
    elif action == "set_clip_speed":
        _, clip = _find_clip(out, _require_str(edit.get("clip_id"), "edit.clip_id"))
        speed = _require_num(edit.get("speed"), "edit.speed")
        if speed <= 0:
            raise CapabilityError("edit.editable_project: speed must be > 0")
        clip["edits"]["speed"] = speed
    elif action == "split_clip":
        track, clip = _find_clip(out, _require_str(edit.get("clip_id"), "edit.clip_id"))
        at = _require_num(edit.get("at_sec"), "edit.at_sec")
        new_id = _require_str(edit.get("new_clip_id"), "edit.new_clip_id")
        if not (clip["timeline_start_sec"] < at < clip["timeline_end_sec"]):
            raise CapabilityError("edit.editable_project: split point must lie strictly inside the clip")
        try:
            _find_clip(out, new_id)
        except CapabilityError:
            pass
        else:
            raise CapabilityError(f"edit.editable_project: new clip id {new_id!r} already exists")
        second = copy.deepcopy(clip)
        second["clip_id"] = new_id
        second["timeline_start_sec"] = at
        if "source_start_sec" in clip and "source_end_sec" in clip:
            frac = (at - clip["timeline_start_sec"]) / (clip["timeline_end_sec"] - clip["timeline_start_sec"])
            mid = clip["source_start_sec"] + frac * (clip["source_end_sec"] - clip["source_start_sec"])
            clip["source_end_sec"] = round(mid, 3)
            second["source_start_sec"] = round(mid, 3)
        clip["timeline_end_sec"] = at
        track["clips"].append(second)
        track["clips"].sort(key=lambda c: c["timeline_start_sec"])
    else:
        raise CapabilityError(f"edit.editable_project: unknown edit action {action!r}")
    _validate_project(out)
    out.setdefault("edit_history", []).append({"sequence": seq, "action": action, "edit": {k: v for k, v in edit.items() if k != "action"}})
    clip_count = sum(len(t["clips"]) for t in out["tracks"])
    out["summary"] = {"track_count": len(out["tracks"]), "clip_count": clip_count}
    return out


def _render(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    result = build_project(params.get("spec"))
    if isinstance(params.get("edit"), dict):
        result = apply_edit(result, params["edit"])
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = out_dir / "editable_project.json"
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report),
        qa={"report_json": str(report), "project_id": result["project_id"], "clip_count": result["summary"]["clip_count"]},
    )


def register_editable_project_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(Capability(
        name="edit.editable_project",
        kind="line",
        aspects=["16:9", "9:16"],
        params_schema={
            "type": "object",
            "properties": {"spec": {"type": "object"}, "edit": {"type": "object"}},
            "required": ["spec"],
            "additionalProperties": False,
        },
        cpu_cost_hint=0.0,
        render=_render,
        has_media_output=False,
        description=(
            "Editable project spec (clean-room): a multi-track project an agent "
            "can read, write and re-edit (rename, retime, move, set text/speed, "
            "split) with history. Spec only; no playback, no desktop shell."
        ),
        line="edit",
    ))
    return ["edit.editable_project"]


register_editable_project_capabilities_once()
