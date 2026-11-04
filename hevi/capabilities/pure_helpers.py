"""Shared pure helpers (no Capability is registered here).

SPEC HELIOS_3O_SPEC_v3_0 section 1.2 sink: several capability
modules used to host small pure functions (grid math, verdict
summaries, prompt-construction resolvers, plan validators) that
other layers also need. Calling them through the hosting element
file made sibling-import graphs claim element-to-element calls
that are really shared-helper uses. The canonical definitions
live here; the origin modules re-export them, so every existing
import path keeps working.
"""

from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Any
from hevi.capabilities.errors import CapabilityError
import re
from hevi.capabilities.asr_normalization import normalized_text_only


# --- from hevi/capabilities/continuation_grid_gate.py ---
GRID_BASE = 5


# --- from hevi/capabilities/continuation_grid_gate.py ---
GRID_STEP = 17


# --- from hevi/capabilities/continuation_grid_gate.py ---
def is_on_grid(frames: int) -> bool:
    """True when ``frames`` falls on the 5 + 17k grid."""
    return (
        isinstance(frames, int)
        and not isinstance(frames, bool)
        and frames >= GRID_BASE
        and (frames - GRID_BASE) % GRID_STEP == 0
    )


# --- from hevi/capabilities/continuation_grid_gate.py ---
def snap_down(frames: int) -> int:
    """Largest grid value at or below ``frames`` (``GRID_BASE`` floor)."""
    if frames <= GRID_BASE:
        return GRID_BASE
    return GRID_BASE + ((frames - GRID_BASE) // GRID_STEP) * GRID_STEP


# --- from hevi/capabilities/continuation_grid_gate.py ---
def snap_up(frames: int) -> int:
    """Smallest grid value at or above ``frames``."""
    if frames <= GRID_BASE:
        return GRID_BASE
    remainder = (frames - GRID_BASE) % GRID_STEP
    if remainder == 0:
        return frames
    return frames + (GRID_STEP - remainder)


# --- from hevi/capabilities/athenaion_world.py ---
HEIGHT_CONSTANTS = {
    "plateau_height": 9.0,
    "plateau_edge_x": -12.0,
    "plateau_softness": 3.5,
    "base": 1.0,
    "hill_amp1": 2.2,
    "hill_amp2": 1.1,
    "mound_amp": 3.0,
    "mound_x": 18.0,
    "mound_z": 10.0,
    "mound_sigma2": 180.0,
}


# --- from hevi/capabilities/athenaion_world.py ---
def height_at(x: float, z: float) -> float:
    """Analytic ground height in metres (Python mirror of the JS page)."""
    c = HEIGHT_CONSTANTS
    plateau = c["plateau_height"] / (1.0 + math.exp((x - c["plateau_edge_x"]) / c["plateau_softness"]))
    hills = (
        c["hill_amp1"] * math.sin(x * 0.09 + 0.7) * math.cos(z * 0.07 + 0.3)
        + c["hill_amp2"] * math.sin(x * 0.23) * math.sin(z * 0.19 + 1.3)
    )
    dx, dz = x - c["mound_x"], z - c["mound_z"]
    mound = c["mound_amp"] * math.exp(-(dx * dx + dz * dz) / c["mound_sigma2"])
    return c["base"] + plateau + hills + mound


# --- from hevi/capabilities/prompt_eval_harness.py ---
def _containment_coverage(expected: str, observed: str) -> float:
    """Share of ``expected`` characters covered by ``observed`` text.

    Longest-common-block coverage (``difflib``), so a line spoken
    inside a longer transcript scores ~1.0 while an unrelated
    transcript scores near 0. Deterministic, offline, text-only.

    ASR-fix P0: the OBSERVED side is normalised before scoring
    (traditional -> simplified plus the audited ASR glossary, via the
    built-in table so the score is reproducible on any machine); the
    EXPECTED script text is used exactly as supplied and is never
    normalised. The 0.80 floor in ``DIALOGUE_COVERAGE_FLOOR`` is
    unchanged. Expected text must therefore be in simplified form,
    as scripts are.
    """
    import difflib

    want = _normalise_text(expected)
    got = _normalise_text(normalized_text_only(observed))
    if not want:
        return 1.0
    if not got:
        return 0.0
    matcher = difflib.SequenceMatcher(None, want, got, autojunk=False)
    covered = sum(block.size for block in matcher.get_matching_blocks())
    return min(1.0, covered / len(want))


# --- from hevi/capabilities/verdict_vocabulary.py ---
def summarise_verdicts(items: Any) -> dict[str, Any]:
    """Overall verdict for a list of check items (all-or-nothing).

    ``fail`` if any item fails; else ``not_checked`` if any item was
    not checked; else ``pass``. Counts are reported so a caller can
    see exactly how much was actually checked.
    """
    if not isinstance(items, list):
        raise CapabilityError(
            "qa.verdict_vocabulary: summarise_verdicts needs a list of "
            "check items"
        )
    counts = {"pass": 0, "fail": 0, "not_checked": 0}
    normalised: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        checked = check_item_verdict(item)
        if not checked["ok"]:
            issues.extend(
                {**i, "item_index": index} for i in checked["issues"])
            continue
        verdict = checked["verdict"]
        assert verdict is not None
        counts[verdict] += 1
        normalised.append({"item_index": index, "verdict": verdict})
    if issues:
        return {"ok": False, "verdict": "fail", "counts": counts,
                "items": normalised, "issues": issues}
    if counts["fail"]:
        overall = "fail"
    elif counts["not_checked"]:
        overall = "not_checked"
    else:
        overall = "pass"
    return {"ok": True, "verdict": overall, "counts": counts,
            "items": normalised, "issues": []}


# --- from hevi/capabilities/manim_render.py ---
DEFAULT_MANIM_PYTHON = "/data/soffy/venvs/manim/bin/python"


# --- from hevi/capabilities/manim_render.py ---
def manim_python() -> Path:
    """Resolve the Manim venv interpreter (env override wins)."""
    return Path(os.environ.get("HEVI_MANIM_PYTHON", DEFAULT_MANIM_PYTHON))


# --- from hevi/capabilities/code_studio_workflow.py ---
def _is_num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


# --- from hevi/capabilities/code_studio_workflow.py ---
def check_beat_alignment(
    events: Any,
    grid: Any,
    tolerance: float = 0.05,
    mode: str | None = None,
) -> dict[str, Any]:
    """Check that cut / sound / picture-change events land on beats.

    Music-first and music-last pass through this same function:
    ``mode`` only records which order the music was fixed in, it
    never changes the tolerance or the check.
    """
    problems: list[str] = []
    if isinstance(grid, dict):
        beats = grid.get("beats") or []
        beat_basis = grid.get("beat_basis", "planned_not_measured")
        measured = bool(grid.get("measured_from_audio", False))
        grid_mode = grid.get("mode")
    elif isinstance(grid, list):
        beats = grid
        beat_basis = "planned_not_measured"
        measured = False
        grid_mode = None
    else:
        beats, beat_basis, measured, grid_mode = [], "planned_not_measured", False, None
    effective_mode = mode or grid_mode
    if effective_mode is not None and effective_mode not in ("music_first", "music_last"):
        problems.append(
            f"mode: must be music_first or music_last, got {effective_mode!r}"
        )
    if not beats:
        problems.append("grid: no beat points in the grid")
    if not _is_num(tolerance) or float(tolerance) < 0:
        problems.append("tolerance: must be a non-negative number")
        tolerance = 0.05
    if not isinstance(events, list) or not events:
        problems.append("events: a non-empty events list is required")
        events = []
    misaligned: list[dict[str, Any]] = []
    checked = 0
    for index, event in enumerate(events):
        if not isinstance(event, dict):
            problems.append(f"events[{index}]: event must be an object")
            continue
        checked += 1
        event_id = event.get("id") or event.get("event_id") or f"event_{index}"
        when = event.get("time_sec", event.get("t_sec", event.get("t")))
        if not _is_num(when):
            problems.append(f"events[{index}] ({event_id}): time_sec is required")
            continue
        if not beats:
            continue
        nearest = min(beats, key=lambda b: abs(float(b) - float(when)))
        deviation = abs(float(when) - float(nearest))
        if deviation > float(tolerance) + 1e-9:
            misaligned.append({
                "event_id": event_id,
                "kind": event.get("kind") or event.get("type"),
                "time_sec": float(when),
                "nearest_beat_sec": float(nearest),
                "deviation_sec": round(deviation, 4),
            })
            problems.append(
                f"events[{index}] ({event_id}): at {when}s, "
                f"{deviation:.3f}s from the nearest beat {nearest}s "
                f"(tolerance {tolerance}s)"
            )
    return {
        "ok": not problems,
        "problems": problems,
        "checked": checked,
        "misaligned": misaligned,
        "tolerance_sec": float(tolerance),
        "mode": effective_mode,
        "beat_basis": beat_basis,
        "measured_from_audio": measured,
        "note": (
            "Beat basis is planned_not_measured unless the grid was "
            "measured from an audio file by a separate step."
        ),
    }


# --- from hevi/capabilities/stable_film_pipeline.py ---
def check_confirmation(confirmation: Any, stage: str) -> dict[str, Any]:
    """Strict confirmation check: ``confirmed`` must be exactly True.

    Anything else -- False, "yes", 1, a missing stage, a missing
    dict -- is a refusal that names the reason. Silence, skipping
    and timeout are not confirmations because they never arrive
    here as ``confirmed is True``.
    """
    if not isinstance(confirmation, dict):
        return {"allowed": False, "stage": stage,
                "reason": "no confirmation supplied (expected a dict)"}
    if confirmation.get("stage") != stage:
        return {"allowed": False, "stage": stage,
                "reason": (
                    f"confirmation stage is {confirmation.get('stage')!r}, "
                    f"not {stage!r}; a confirmation for one stage never "
                    "unlocks another stage"
                )}
    if confirmation.get("confirmed") is not True:
        return {"allowed": False, "stage": stage,
                "reason": "confirmed is not exactly True; synthesis/release is refused"}
    return {"allowed": True, "stage": stage, "reason": ""}


# --- from hevi/capabilities/task_recovery_gate.py ---
CHECKPOINT_STATES = ("interrupted", "paused", "failed")


# --- from hevi/capabilities/task_recovery_gate.py ---
def _task_recovery_issue(code: str, detail: str, **extra: Any) -> dict[str, Any]:
    issue = {"code": code, "detail": f"qa.task_recovery_gate: {detail}"}
    issue.update(extra)
    return issue


# --- from hevi/capabilities/task_recovery_gate.py ---
def _segment_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list):
        raise CapabilityError(
            f"qa.task_recovery_gate: {field} must be a list of segment ids"
        )
    for item in value:
        if not isinstance(item, str) or not item:
            raise CapabilityError(
                f"qa.task_recovery_gate: every {field} entry must be a "
                "non-empty segment id string"
            )
    if len(set(value)) != len(value):
        raise CapabilityError(
            f"qa.task_recovery_gate: {field} lists a segment twice"
        )
    return list(value)


# --- from hevi/capabilities/task_recovery_gate.py ---
def check_task_recovery(
    plan: Any,
    *,
    checkpoint: Any = None,
) -> dict[str, Any]:
    """Check a recovery plan against its checkpoint record.

    ``plan`` carries ``task_id``, ``segments`` (the full segment
    list), ``segments_to_run`` and ``rerun_from_start``. The
    checkpoint may be passed separately or carried inside the
    plan under ``checkpoint``. Returns a report with ``ok`` and
    the problems.
    """
    if not isinstance(plan, dict):
        raise CapabilityError(
            "qa.task_recovery_gate: plan must be an object"
        )
    record = checkpoint if checkpoint is not None else plan.get("checkpoint")
    problems: list[dict[str, Any]] = []
    task_id = plan.get("task_id")
    if not isinstance(task_id, str) or not task_id:
        raise CapabilityError(
            "qa.task_recovery_gate: plan needs a non-empty task_id string"
        )
    segments = _segment_list(plan.get("segments", []), "segments")
    to_run = _segment_list(plan.get("segments_to_run", []), "segments_to_run")

    if record is None:
        problems.append(
            _task_recovery_issue(
                "missing_checkpoint",
                f"task {task_id!r} claims recovery but carries no "
                "checkpoint record; without one it is a restart, "
                "not a recovery",
                task_id=task_id,
            )
        )
        return {
            "ok": False,
            "task_id": task_id,
            "problems": problems,
        }
    if not isinstance(record, dict):
        raise CapabilityError(
            "qa.task_recovery_gate: checkpoint must be an object"
        )
    if record.get("task_id") != task_id:
        problems.append(
            _task_recovery_issue(
                "checkpoint_task_mismatch",
                "checkpoint belongs to task "
                f"{record.get('task_id')!r}, not {task_id!r}",
                task_id=task_id,
                checkpoint_task_id=record.get("task_id"),
            )
        )
    state = record.get("state")
    if state not in CHECKPOINT_STATES:
        problems.append(
            _task_recovery_issue(
                "checkpoint_not_resumable",
                f"checkpoint state {state!r} is not resumable; only "
                f"{list(CHECKPOINT_STATES)} checkpoints resume",
                state=state,
            )
        )
    completed = _segment_list(
        record.get("completed_segments", []), "completed_segments"
    )
    unknown_completed = [s for s in completed if s not in segments]
    if unknown_completed:
        problems.append(
            _task_recovery_issue(
                "checkpoint_unknown_segment",
                "checkpoint lists completed segments that are not in "
                f"the plan: {unknown_completed}",
                segments=unknown_completed,
            )
        )
    rerun = [s for s in to_run if s in completed]
    if rerun:
        problems.append(
            _task_recovery_issue(
                "reruns_completed_segment",
                "recovery re-runs finished segments instead of "
                f"skipping them: {rerun}",
                segments=rerun,
            )
        )
    unknown_run = [s for s in to_run if s not in segments]
    if unknown_run:
        problems.append(
            _task_recovery_issue(
                "unknown_segment_to_run",
                f"plan schedules segments that do not exist: {unknown_run}",
                segments=unknown_run,
            )
        )
    if plan.get("rerun_from_start") is True:
        problems.append(
            _task_recovery_issue(
                "restart_claimed_as_recovery",
                "plan restarts from the beginning and calls it "
                "recovery; a recovery resumes from its checkpoint",
            )
        )
    position = record.get("position")
    if position is not None:
        if position not in segments:
            problems.append(
                _task_recovery_issue(
                    "checkpoint_position_unknown",
                    f"checkpoint position {position!r} is not a segment "
                    "of this task",
                    position=position,
                )
            )
        elif position in completed:
            problems.append(
                _task_recovery_issue(
                    "checkpoint_position_completed",
                    f"checkpoint position {position!r} is already "
                    "completed; resuming there re-runs finished work",
                    position=position,
                )
            )
        elif position not in to_run:
            problems.append(
                _task_recovery_issue(
                    "checkpoint_position_not_scheduled",
                    f"checkpoint position {position!r} is not in the "
                    "plan's remaining work",
                    position=position,
                )
            )
    if record.get("recorded_at") is None:
        problems.append(
            _task_recovery_issue(
                "checkpoint_undated",
                "checkpoint carries no recorded_at time; an undated "
                "checkpoint cannot be ordered against later work",
            )
        )
    return {
        "ok": not problems,
        "task_id": task_id,
        "completed_segments": completed,
        "problems": problems,
    }


# --- from hevi/capabilities/h3_frame_align_gate.py ---
FPS = 24


# --- from hevi/capabilities/h3_frame_align_gate.py ---
GRID_FLOOR_FRAMES = 5


# --- from hevi/capabilities/h3_frame_align_gate.py ---
def _frame_align_issue(code: str, detail: str, **extra: Any) -> dict[str, Any]:
    issue = {"code": code, "detail": f"qa.h3_frame_align_gate: {detail}"}
    issue.update(extra)
    return issue


# --- from hevi/capabilities/h3_frame_align_gate.py ---
def requested_frames(duration_s: float) -> int:
    """Frames before snapping: ``max(5, round(duration * 24))``."""
    return max(GRID_FLOOR_FRAMES, round(duration_s * FPS))


# --- from hevi/capabilities/h3_frame_align_gate.py ---
def aligned_frames(duration_s: float) -> int:
    """Frames after snapping up to the 5 + 17k grid."""
    return snap_up(requested_frames(duration_s))


# --- from hevi/capabilities/h3_frame_align_gate.py ---
def check_frame_alignment(plan: Any) -> dict[str, Any]:
    """Judge one single-segment plan's frame alignment.

    ``plan`` is an object with ``duration_s`` (requested seconds)
    and ``frames`` (declared frame count). ``snap_direction``
    must be ``"up"`` when present. When the snapped length
    differs from the request, ``declared_output_s`` must state
    the actual output duration (``frames / 24``). Returns ``ok``
    / ``issues`` / ``alignment``.
    """
    issues: list[dict[str, Any]] = []
    if not isinstance(plan, dict):
        return {
            "ok": False,
            "issues": [_frame_align_issue("plan_not_object", "frame plan must be an object")],
            "alignment": None,
        }
    duration_s = plan.get("duration_s")
    frames = plan.get("frames")
    if not isinstance(duration_s, (int, float)) or isinstance(duration_s, bool) or duration_s <= 0:
        issues.append(_frame_align_issue("duration_undeclared", "duration_s must be a positive number"))
        return {"ok": False, "issues": issues, "alignment": None}
    if not isinstance(frames, int) or isinstance(frames, bool):
        issues.append(_frame_align_issue("frames_undeclared", "frames must be an integer"))
        return {"ok": False, "issues": issues, "alignment": None}
    expected = aligned_frames(duration_s)
    snap_direction = plan.get("snap_direction", "up")
    if snap_direction != "up":
        issues.append(
            _frame_align_issue(
                "snap_direction_not_up",
                f"snap_direction must be 'up', got {snap_direction!r}; "
                "snapping down silently shortens the segment",
                snap_direction=snap_direction,
            )
        )
    if frames != expected:
        issues.append(
            _frame_align_issue(
                "frame_count_off_grid",
                f"frames must be the snapped-up count {expected} for "
                f"{duration_s}s, got {frames}",
                frames=frames,
                expected=expected,
                on_grid=is_on_grid(frames),
            )
        )
    output_s = frames / FPS
    declared_output = plan.get("declared_output_s")
    if abs(output_s - duration_s) > 1e-9:
        if declared_output is None:
            issues.append(
                _frame_align_issue(
                    "undeclared_output_stretch",
                    f"snapped output is {output_s:.3f}s, not the "
                    f"requested {duration_s}s; declared_output_s "
                    "must state the actual output duration",
                    output_s=output_s,
                )
            )
        elif abs(declared_output - output_s) > 1e-9:
            issues.append(
                _frame_align_issue(
                    "output_duration_mismatch",
                    f"declared_output_s {declared_output} does not "
                    f"match frames/24 = {output_s:.3f}",
                    output_s=output_s,
                )
            )
    return {
        "ok": not issues,
        "issues": issues,
        "alignment": {
            "duration_s": duration_s,
            "requested_frames": requested_frames(duration_s),
            "frames": frames,
            "expected_frames": expected,
            "output_s": output_s,
            "on_grid": is_on_grid(frames),
        },
    }


# --- from hevi/capabilities/h3_stale_defaults_gate.py ---
def _stale_defaults_issue(code: str, detail: str, **extra: Any) -> dict[str, Any]:
    issue = {"code": code, "detail": f"qa.h3_stale_defaults_gate: {detail}"}
    issue.update(extra)
    return issue


# --- from hevi/capabilities/h3_stale_defaults_gate.py ---
def check_stale_defaults(plan: Any) -> dict[str, Any]:
    """Judge one plan's effective configuration for stale values.

    ``plan`` is an object with ``outer_panel`` (the current
    caller-set values), ``inner_defaults`` (values left inside a
    nested sub-process), and ``effective`` (the configuration
    that would actually run). Every effective field that equals
    an inner default while differing from the outer panel fails
    as ``stale_inner_defaults`` and names the field. A plan
    without an outer panel, or without declared inner defaults,
    cannot be judged and fails. Returns ``ok`` / ``issues`` /
    ``stale_fields``.
    """
    issues: list[dict[str, Any]] = []
    stale_fields: list[str] = []
    if not isinstance(plan, dict):
        return {
            "ok": False,
            "issues": [_stale_defaults_issue("plan_not_object", "plan must be an object")],
            "stale_fields": stale_fields,
        }
    outer = plan.get("outer_panel")
    inner = plan.get("inner_defaults")
    effective = plan.get("effective")
    if not isinstance(outer, dict) or not outer:
        issues.append(
            _stale_defaults_issue(
                "outer_panel_undeclared",
                "outer_panel (current caller-set values) is required",
            )
        )
    if not isinstance(inner, dict) or not inner:
        issues.append(
            _stale_defaults_issue(
                "inner_defaults_undeclared",
                "inner_defaults (nested sub-process leftovers) must "
                "be declared so staleness can be checked",
            )
        )
    if not isinstance(effective, dict) or not effective:
        issues.append(
            _stale_defaults_issue("effective_undeclared", "effective configuration is required")
        )
    if issues:
        return {"ok": False, "issues": issues, "stale_fields": stale_fields}
    for field, value in effective.items():
        if field in inner and value == inner[field] and outer.get(field) != value:
            stale_fields.append(field)
            issues.append(
                _stale_defaults_issue(
                    "stale_inner_defaults",
                    f"effective field {field!r} equals a stale nested "
                    "default and differs from the outer panel; clean "
                    "the plan so the outer panel governs",
                    field=field,
                    value=value,
                )
            )
    return {"ok": not issues, "issues": issues, "stale_fields": stale_fields}


# --- from hevi/capabilities/scene_reference.py ---
H3_FPS = 24


# --- from hevi/capabilities/scene_reference.py ---
H3_FRAME_STEP = 17


# --- from hevi/capabilities/scene_reference.py ---
H3_FRAME_OFFSET = 5


# --- from hevi/capabilities/scene_reference.py ---
def resolve_picture_binding(binding: Any, what: str = "reference binding") -> dict[str, Any]:
    """Validate one Picture -> file binding. Returns ``{file, sha256}``.

    ``file`` must be a non-empty string and ``sha256`` a 64-hex digest
    of the file's bytes. A local filesystem path (no URL scheme) must
    exist on disk; a URL is accepted on its hash alone, because the
    file lives elsewhere -- the hash is what the executor checks.
    """
    if not isinstance(binding, dict):
        raise CapabilityError(
            f"pipeline.scene_reference: {what} must be an object with 'file' and 'sha256'")
    file = binding.get("file")
    sha = binding.get("sha256")
    if not isinstance(file, str) or not file.strip():
        raise CapabilityError(f"pipeline.scene_reference: {what} needs a non-empty 'file'")
    if not isinstance(sha, str) or not _SHA256_RE.match(sha.strip()):
        raise CapabilityError(
            f"pipeline.scene_reference: {what} needs a 64-hex 'sha256' for {file!r}")
    file = file.strip()
    if "://" not in file:
        path = Path(file)
        if not path.exists():
            raise CapabilityError(
                f"pipeline.scene_reference: {what} file does not exist: {file!r}")
    return {"file": file, "sha256": sha.strip()}


# --- from hevi/capabilities/scene_reference.py ---
def resolve_picture_bindings(bindings: Any, *, what: str = "reference bindings") -> dict[int, dict[str, Any]]:
    """Validate a Picture-number -> binding map. Keys are ints or digit strings."""
    if not isinstance(bindings, dict):
        raise CapabilityError(f"pipeline.scene_reference: {what} must be an object")
    out: dict[int, dict[str, Any]] = {}
    for key, value in bindings.items():
        try:
            number = int(key)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            raise CapabilityError(
                f"pipeline.scene_reference: {what} key {key!r} is not a picture number") from None
        if number < 1:
            raise CapabilityError(
                f"pipeline.scene_reference: {what} picture number must be >= 1, got {number}")
        out[number] = resolve_picture_binding(value, f"{what} picture {number}")
    return out


# --- from hevi/capabilities/scene_reference.py ---
def resolve_character_anchor(name: str, anchors: Any) -> dict[str, Any]:
    """Resolve one character's confirmed anchor from an anchors map.

    Accepted shapes (both must be confirmed by a human -- an
    unconfirmed or missing anchor fails, it never falls back to a
    bare name):
    * a ``qa.character_anchor_gate`` sheet: ``{"anchor": {"file",
      "sha256", "look_snapshot", "confirmed": true, ...}}``;
    * a plain record: ``{"look_snapshot"|"look"|"description",
      "file", "sha256", "confirmed": true}`` with optional
      ``"wardrobe"``.
    Returns ``{name, look, wardrobe, file, sha256}``.
    """
    if not isinstance(anchors, dict) or name not in anchors:
        raise CapabilityError(
            f"pipeline.scene_reference: character {name!r} has no confirmed anchor; "
            "a bare name is not a prompt-ready character")
    record = anchors[name]
    if not isinstance(record, dict):
        raise CapabilityError(
            f"pipeline.scene_reference: anchor for {name!r} must be an object")
    anchor = record.get("anchor") if isinstance(record.get("anchor"), dict) else record
    if anchor.get("confirmed") is not True:
        raise CapabilityError(
            f"pipeline.scene_reference: anchor for {name!r} is not confirmed; "
            "unconfirmed anchors never reach generation")
    look = anchor.get("look_snapshot") or anchor.get("look") or anchor.get("description")
    if not isinstance(look, str) or not look.strip():
        raise CapabilityError(
            f"pipeline.scene_reference: anchor for {name!r} carries no look description")
    binding = resolve_picture_binding(
        {"file": anchor.get("file"), "sha256": anchor.get("sha256")},
        f"anchor for {name!r}")
    wardrobe = anchor.get("wardrobe")
    if wardrobe is not None and (not isinstance(wardrobe, str) or not wardrobe.strip()):
        raise CapabilityError(
            f"pipeline.scene_reference: anchor wardrobe for {name!r} must be a non-empty string")
    return {"name": name, "look": look.strip(),
            "wardrobe": wardrobe.strip() if isinstance(wardrobe, str) else None,
            "file": binding["file"], "sha256": binding["sha256"]}


# --- from hevi/capabilities/scene_reference.py ---
def canonical_frame_count(seconds: float, fps: float = H3_FPS, route: str = "h3") -> int:
    """Frame count for ``seconds`` on one named execution route.

    ``route="h3"`` snaps to the 17k+5 lattice; ``route="fasth3_local"``
    rounds to the nearest frame; any other route name also rounds
    and is recorded by the caller. Plan arithmetic only.
    """
    for value, what in ((seconds, "seconds"), (fps, "fps")):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise CapabilityError(f"pipeline.scene_reference: {what} must be a finite number")
    if seconds <= 0 or fps <= 0:
        raise CapabilityError("pipeline.scene_reference: seconds and fps must be positive")
    if route == "h3":
        frames = max(H3_FRAME_OFFSET, int(round(seconds * fps)))
        return frames + (H3_FRAME_OFFSET - frames % H3_FRAME_STEP) % H3_FRAME_STEP
    if not isinstance(route, str) or not route.strip():
        raise CapabilityError("pipeline.scene_reference: route must be a non-empty string")
    return max(1, int(round(seconds * fps)))


# --- from hevi/capabilities/prompt_eval_harness.py ---
_PUNCT = " \t\n\r，。、；：！？,.!?;:\"'“”‘’()（）[]【】"


# --- from hevi/capabilities/prompt_eval_harness.py ---
def _normalise_text(text: str) -> str:
    return "".join(ch for ch in str(text) if ch not in _PUNCT).lower()


# --- from hevi/capabilities/verdict_vocabulary.py ---
def check_item_verdict(item: Any) -> dict[str, Any]:
    """Normalise one check item's verdict field.

    Accepts ``verdict`` (vocabulary or legacy string) or ``pass``
    (``True``/``False``/``None``). An item carrying neither, or
    carrying both in disagreement, fails the normalisation.
    """
    if not isinstance(item, dict):
        return {"ok": False, "verdict": None, "issues": [{
            "code": "item_not_object",
            "detail": "qa.verdict_vocabulary: check item must be an object",
        }]}
    verdicts: list[str] = []
    issues: list[dict[str, Any]] = []
    if "verdict" in item:
        try:
            verdicts.append(normalise_verdict(item["verdict"]))
        except CapabilityError as exc:
            issues.append({"code": "bad_verdict", "detail": str(exc)})
    if "pass" in item:
        try:
            verdicts.append(normalise_verdict(item["pass"]))
        except CapabilityError as exc:
            issues.append({"code": "bad_verdict", "detail": str(exc)})
    if not verdicts and not issues:
        issues.append({
            "code": "verdict_missing",
            "detail": "qa.verdict_vocabulary: check item carries neither "
                     "'verdict' nor 'pass'; an unjudged item must say "
                     "not_checked, not stay silent",
        })
    if len(verdicts) > 1 and verdicts[0] != verdicts[1]:
        issues.append({
            "code": "verdict_disagreement",
            "detail": "qa.verdict_vocabulary: item 'verdict' and 'pass' "
                     f"disagree ({verdicts[0]} vs {verdicts[1]}); fix the "
                     "item instead of guessing which one wins",
        })
    verdict = verdicts[0] if verdicts else None
    return {"ok": not issues, "verdict": verdict, "issues": issues}


# --- from hevi/capabilities/scene_reference.py ---
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


# --- from hevi/capabilities/verdict_vocabulary.py ---
_LEGACY_MAP: dict[Any, str] = {
    True: "pass",
    False: "fail",
    None: "not_checked",
    "pass": "pass",
    "fail": "fail",
    "not_checked": "not_checked",
    "skipped": "not_checked",
    "planned_not_measured": "not_checked",
}


# --- from hevi/capabilities/verdict_vocabulary.py ---
def normalise_verdict(value: Any) -> str:
    """One legacy verdict value to the single vocabulary. Raises otherwise."""
    if isinstance(value, str):
        key: Any = value.strip().lower()
    else:
        key = value
    # bool is a subclass of int: check identity first via the map keys.
    if key in _LEGACY_MAP and not isinstance(key, (int, float)):
        return _LEGACY_MAP[key]
    if value is True:
        return "pass"
    if value is False:
        return "fail"
    if value is None:
        return "not_checked"
    raise CapabilityError(
        "qa.verdict_vocabulary: "
        f"{value!r} is not a verdict; use pass, fail, or not_checked "
        "(legacy: true/false/null, skipped, planned_not_measured)"
    )
