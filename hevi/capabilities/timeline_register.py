"""Generate-into-timeline: one generation call lands on the edit timeline.

Pipeline-side only (no desktop UI). A generation result is not a loose
file: registering it appends one entry to a project's timeline, and the
entry carries at least the clip id, the track position, the source
model, and the cost. The timeline is plain JSON, so a later run can
load the same project file and keep generating onto the SAME track:
the next clip starts where the previous clip on that track ended.
Nothing already on the timeline is dropped or re-timed by a new
registration, and a duplicate clip id is an error, not a silent
overwrite.

Track model (deliberately small):
* a project has named tracks; the default track is ``video``.
* a clip occupies [timeline_start_sec, timeline_end_sec) on its track,
  computed from the durations of the clips already on that track.
* ``register_generation`` with no explicit track continues the
  project's last-used track, so "generate again" after a reload
  continues the same track instead of starting a second timeline.

This module is written from scratch for hevi; it does not copy, port,
or reimplement any external editor's timeline code.
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
DEFAULT_TRACK = "video"


def create_timeline(project_id: str) -> dict[str, Any]:
    """Empty timeline state for a project (in memory, JSON-serializable)."""
    if not isinstance(project_id, str) or not project_id.strip():
        raise CapabilityError("edit.timeline_register: project_id must be a non-empty string")
    return {
        "project_id": project_id.strip(),
        "clips": [],
        "last_track": DEFAULT_TRACK,
        "version": 1,
    }


def _validate_timeline(state: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(state, dict) or not isinstance(state.get("clips"), list):
        raise CapabilityError("edit.timeline_register: timeline state must be a dict with a clips list")
    return state


def load_timeline(path: str | Path) -> dict[str, Any]:
    """Load a timeline JSON file; a missing file is an error, not an empty timeline."""
    path = Path(path)
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise CapabilityError(f"edit.timeline_register: cannot load timeline {path}: {exc}") from exc
    return _validate_timeline(state)


def save_timeline(state: dict[str, Any], path: str | Path) -> str:
    """Write timeline state to JSON (sorted keys, so reloads are stable)."""
    _validate_timeline(state)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    return str(path)


def track_end_sec(state: dict[str, Any], track: str) -> float:
    """End of the last clip on a track, or 0.0 when the track is empty."""
    _validate_timeline(state)
    ends = [float(c["timeline_end_sec"]) for c in state["clips"] if c.get("track") == track]
    return max(ends) if ends else 0.0


def next_start_sec(state: dict[str, Any], track: str | None = None) -> float:
    """Where the next clip on a track starts (continuation point)."""
    _validate_timeline(state)
    track = track or str(state.get("last_track") or DEFAULT_TRACK)
    return track_end_sec(state, track)


def register_generation(state: dict[str, Any], clip: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Append one generation result to the timeline.

    Returns ``(new_state, entry)``. The input state is not mutated;
    a caller that discards the new state has changed nothing.
    Required clip fields: ``clip_id`` (unique in this project),
    ``file`` (artifact path or name), ``duration_sec`` (> 0).
    Optional: ``track`` (defaults to the last-used track),
    ``source_model``, ``source_capability``, ``estimated_cost_usd``
    (a float, or None when the price was unknown -- never invented).
    """
    _validate_timeline(state)
    if not isinstance(clip, dict):
        raise CapabilityError("edit.timeline_register: clip must be a dict")
    clip_id = clip.get("clip_id")
    if not isinstance(clip_id, str) or not clip_id.strip():
        raise CapabilityError("edit.timeline_register: clip requires a non-empty string clip_id")
    clip_id = clip_id.strip()
    if any(c.get("clip_id") == clip_id for c in state["clips"]):
        raise CapabilityError(f"edit.timeline_register: duplicate clip_id {clip_id!r} in this project")
    file_ref = clip.get("file")
    if not isinstance(file_ref, str) or not file_ref.strip():
        raise CapabilityError(f"edit.timeline_register: clip {clip_id!r} requires a non-empty file reference")
    duration = clip.get("duration_sec")
    if isinstance(duration, bool) or not isinstance(duration, (int, float)) or float(duration) <= 0:
        raise CapabilityError(f"edit.timeline_register: clip {clip_id!r} requires duration_sec > 0")
    track = clip.get("track") or state.get("last_track") or DEFAULT_TRACK
    if not isinstance(track, str) or not track.strip():
        raise CapabilityError(f"edit.timeline_register: clip {clip_id!r} requires a non-empty track")
    track = track.strip()
    cost = clip.get("estimated_cost_usd")
    if cost is not None and (isinstance(cost, bool) or not isinstance(cost, (int, float)) or float(cost) < 0):
        raise CapabilityError(f"edit.timeline_register: clip {clip_id!r} estimated_cost_usd must be a non-negative number or None")
    start = track_end_sec(state, track)
    entry = {
        "clip_id": clip_id,
        "track": track,
        "file": file_ref.strip(),
        "duration_sec": float(duration),
        "timeline_start_sec": start,
        "timeline_end_sec": start + float(duration),
        "source_model": clip.get("source_model"),
        "source_capability": clip.get("source_capability"),
        "estimated_cost_usd": (float(cost) if cost is not None else None),
        "index": len(state["clips"]),
    }
    new_state = copy.deepcopy(state)
    new_state["clips"].append(entry)
    new_state["last_track"] = track
    return new_state, entry


def append_generation(state: dict[str, Any], clip: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Alias for ``register_generation``: (new_state, entry) in one call."""
    return register_generation(state, clip)


def read_timeline(state: dict[str, Any]) -> dict[str, Any]:
    """Readable snapshot: clips in timeline order, per-track totals."""
    _validate_timeline(state)
    clips = sorted(state["clips"], key=lambda c: (c["track"], c["timeline_start_sec"]))
    tracks: dict[str, Any] = {}
    for clip in state["clips"]:
        track = tracks.setdefault(clip["track"], {"clip_count": 0, "total_duration_sec": 0.0})
        track["clip_count"] += 1
        track["total_duration_sec"] = max(track["total_duration_sec"], float(clip["timeline_end_sec"]))
    return {
        "project_id": state.get("project_id"),
        "clip_count": len(state["clips"]),
        "clips": copy.deepcopy(clips),
        "tracks": tracks,
        "last_track": state.get("last_track"),
    }


def _resolve_state(params: dict[str, Any], out_dir: Path) -> tuple[dict[str, Any], Path]:
    timeline_path = params.get("timeline_path")
    if timeline_path:
        path = Path(str(timeline_path))
        if path.exists():
            return load_timeline(path), path
        state = create_timeline(str(params.get("project_id") or "project"))
        return state, path
    return create_timeline(str(params.get("project_id") or "project")), Path(out_dir) / "timeline.json"


def _render(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    action = str(params.get("action") or "register")
    state, path = _resolve_state(params, out_dir)
    if action == "register":
        fresh, entry = register_generation(state, {
            "clip_id": params["clip_id"],
            "file": params["file"],
            "duration_sec": params["duration_sec"],
            "track": params.get("track"),
            "source_model": params.get("source_model"),
            "source_capability": params.get("source_capability"),
            "estimated_cost_usd": params.get("estimated_cost_usd"),
        })
        save_timeline(fresh, path)
        payload: dict[str, Any] = {"action": "register", "entry": entry, "timeline": read_timeline(fresh)}
    elif action == "read":
        payload = {"action": "read", "timeline": read_timeline(state)}
    else:
        raise CapabilityError(f"edit.timeline_register: unknown action {action!r}")
    report = Path(out_dir) / "timeline_register.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report),
        qa={"report_json": str(report), "timeline_json": str(path), **payload},
    )


def register_timeline_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="edit.timeline_register",
            kind="line",
            aspects=["16:9", "9:16", "1:1"],
            params_schema={
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["register", "read"]},
                    "project_id": {"type": "string"},
                    "timeline_path": {"type": "string"},
                    "clip_id": {"type": "string"},
                    "file": {"type": "string"},
                    "duration_sec": {"type": "number", "exclusiveMinimum": 0},
                    "track": {"type": "string"},
                    "source_model": {"type": "string"},
                    "source_capability": {"type": "string"},
                    "estimated_cost_usd": {"type": ["number", "null"]},
                },
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Generate-into-timeline: one generation result is "
                "registered onto a project's edit timeline with clip id, "
                "track position, source model and cost. Reloading the "
                "same timeline file continues the same track; new clips "
                "start where the previous clip on that track ended, and "
                "existing clips are never dropped or re-timed."
            ),
            line="edit_assemble",
        )
    )
    return ["edit.timeline_register"]


register_timeline_capabilities_once()
