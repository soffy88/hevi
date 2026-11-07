"""Dance action-event extraction (``qa.dance_action_events``).

Clean-room rewrite of the *method* described in
``hevi-vs-code-stage-mv.md`` section 4: dance action events are
recovered from pose-keypoint time series by differencing, not
from pixels and not from music. This module extracts events
from an offline keypoint contract only. It performs no pose
estimation itself: there is no mediapipe dependency in this
environment (see :func:`pose_backend_status`), no video is read
for keypoints, and a request that supplies only a video path
fails instead of pretending to estimate a pose.

Event model (four types only):

* ``footstep`` -- an ankle reaches its lowest point (local
  maximum of ankle y in image coordinates, y growing downward)
  with enough descent and ascent around it.
* ``turn`` -- the shoulder line narrows to a local minimum
  (the body turns sideways, so the projected shoulder width
  shrinks) with enough narrowing on both sides.
* ``raise_arm`` -- a wrist reaches its highest point (local
  minimum of wrist y) while lifted above the shoulder line.
* ``hold`` -- motion stops: mean joint speed stays below the
  stillness bar for a run of frames that follows motion.
  A sequence that is still from its first frame is not a
  hold; a hold is *stopping*, so motion must precede it.

Every event carries ``type``, ``t`` (seconds, integer frame
math ``t = floor(frame) / fps``, the same discipline as
``qa.deterministic_render_gate``), ``frame``, ``confidence``
in [0, 1] and ``source: "pose_delta"``. Signals weaker than
the full threshold but above half of it are reported as
``candidates``: they are never emitted as events and never
trigger anything downstream. Events whose confidence is below
``confidence_floor`` are likewise demoted to candidates.

Measurement basis is recorded honestly on every report:
``human_measured`` is always ``False`` for this module --
keypoints are supplied offline, and the only measured run in
this graft uses code-generated synthetic video (see
:func:`generate_synthetic_dance`), whose keypoints come from
the same generator script that draws the frames. Synthetic
results are labelled ``synthetic_video`` and must never be
reported as human-dancer measurements. Real-human measurement
remains an open residual: it needs a CPU pose estimator and
a labelled human dance clip, neither of which exists here.

Failure contract: malformed keypoint input (not a JSON
object, no non-empty frame list, bad fps, frames out of
order, a frame time that disagrees with ``frame / fps``, a
missing or non-numeric required joint, a joint confidence
below the usable bar) raises :class:`CapabilityError`.
Well-formed input with no detectable events returns an
empty ``events`` list with ``verdict: "pass"`` -- absence of
events is a finding, not an error. Scoring a detection
against ground truth (see :func:`score_events`) never raises
for a low F1; a low F1 is reported, not hidden.
"""

from __future__ import annotations

import hashlib
import json
import math
import shutil
import subprocess
from fractions import Fraction
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

EVENT_TYPES = ("footstep", "turn", "raise_arm", "hold")

REQUIRED_JOINTS = (
    "ankle_left",
    "ankle_right",
    "wrist_left",
    "wrist_right",
    "shoulder_left",
    "shoulder_right",
    "hip_left",
    "hip_right",
)

# Hevi-chosen defaults, calibrated on the synthetic fixture in
# generate_synthetic_dance (320x240, fps 10). They are pixel
# thresholds at the declared frame size and must be
# re-calibrated on real measurements before any production use.
# No self-reported number from the source article is used here.
DEFAULT_THRESHOLDS: dict[str, float] = {
    "footstep_min_drop_px": 6.0,
    "footstep_min_slope_px": 4.0,
    "turn_min_narrow_px": 12.0,
    "raise_min_lift_px": 20.0,
    "raise_min_prominence_px": 8.0,
    "hold_max_speed_px_per_frame": 1.0,
    "hold_min_frames": 5,
    "peak_window_frames": 2,
    "min_separation_frames": 3,
    "joint_confidence_min": 0.3,
}

DEFAULT_CONFIDENCE_FLOOR = 0.5


def _is_num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def pose_backend_status() -> dict[str, Any]:
    """Report the pose-estimation backend situation honestly.

    No pose estimator is installed or attempted here. Pixel
    pose estimation is unavailable until a CPU estimator is
    chosen and vendored; keypoints must be supplied offline.
    """
    try:
        import mediapipe  # noqa: F401

        available = True
    except Exception:
        available = False
    return {
        "mediapipe_available": available,
        "backend": "offline_keypoint_contract",
        "pixel_pose_estimation": "unavailable",
        "human_measured": False,
        "note": (
            "No pose estimator is installed; this capability "
            "extracts events from supplied keypoints only and "
            "never estimates a pose from video pixels."
            if not available
            else "mediapipe importable, but this capability still "
            "extracts from supplied keypoints only; pixel "
            "estimation is not wired in."
        ),
    }


def frame_time(frame: int, fps: int) -> float:
    """Frame time as exact integer math: floor(frame) / fps."""
    if not isinstance(frame, int) or isinstance(frame, bool) or frame < 0:
        raise CapabilityError("qa.dance_action_events: frame must be a non-negative integer")
    if not isinstance(fps, int) or isinstance(fps, bool) or fps <= 0:
        raise CapabilityError("qa.dance_action_events: fps must be a positive integer")
    return float(Fraction(frame, fps))


def _resolve_thresholds(overrides: Any) -> dict[str, float]:
    thresholds = dict(DEFAULT_THRESHOLDS)
    if overrides is None:
        return thresholds
    if not isinstance(overrides, dict):
        raise CapabilityError("qa.dance_action_events: thresholds must be a JSON object")
    for key, value in overrides.items():
        if key not in DEFAULT_THRESHOLDS:
            raise CapabilityError(
                f"qa.dance_action_events: unknown threshold {key!r}; "
                f"known: {sorted(DEFAULT_THRESHOLDS)}"
            )
        if not _is_num(value) or float(value) < 0:
            raise CapabilityError(
                f"qa.dance_action_events: threshold {key!r} must be a non-negative number"
            )
        thresholds[key] = float(value)
    return thresholds


def _joint(frame: dict[str, Any], name: str, frame_no: Any, conf_min: float) -> tuple[float, float]:
    joints = frame.get("joints")
    if not isinstance(joints, dict):
        raise CapabilityError(
            f"qa.dance_action_events: frame {frame_no!r} has no 'joints' object; "
            "keypoint input is required"
        )
    point = joints.get(name)
    if not isinstance(point, dict):
        raise CapabilityError(
            f"qa.dance_action_events: frame {frame_no!r} is missing required joint {name!r}; "
            "missing keypoints fail, they are never interpolated"
        )
    x, y = point.get("x"), point.get("y")
    if not _is_num(x) or not _is_num(y):
        raise CapabilityError(
            f"qa.dance_action_events: frame {frame_no!r} joint {name!r} needs numeric x and y"
        )
    conf = point.get("confidence")
    if conf is not None:
        if not _is_num(conf) or not 0.0 <= float(conf) <= 1.0:
            raise CapabilityError(
                f"qa.dance_action_events: frame {frame_no!r} joint {name!r} "
                "confidence must be in [0, 1]"
            )
        if float(conf) < conf_min:
            raise CapabilityError(
                f"qa.dance_action_events: frame {frame_no!r} joint {name!r} "
                f"confidence {float(conf):g} is below the usable bar "
                f"{conf_min:g}; low-confidence keypoints fail, they are "
                "never treated as present"
            )
    return float(x), float(y)


def validate_keypoint_input(keypoints: Any) -> dict[str, Any]:
    """Validate the offline keypoint contract; return normalised frames.

    Raises :class:`CapabilityError` on any missing or
    inconsistent input, including a bare ``video_path`` with
    no keypoints (no estimator exists to read it).
    """
    if not isinstance(keypoints, dict):
        raise CapabilityError(
            "qa.dance_action_events: keypoint input must be a JSON object; "
            "a video path alone is not keypoint input (no pose backend)"
        )
    if keypoints.get("video_path") is not None and keypoints.get("frames") is None:
        raise CapabilityError(
            "qa.dance_action_events: only a video path was supplied and no "
            "keypoints; pixel pose estimation is unavailable, so the "
            "request fails instead of pretending to estimate a pose"
        )
    fps = keypoints.get("fps")
    if not isinstance(fps, int) or isinstance(fps, bool) or fps <= 0:
        raise CapabilityError("qa.dance_action_events: 'fps' must be a positive integer")
    width, height = keypoints.get("width"), keypoints.get("height")
    for field, value in (("width", width), ("height", height)):
        if not _is_num(value) or float(value) <= 0:
            raise CapabilityError(
                f"qa.dance_action_events: '{field}' must be a positive number "
                "(keypoint pixel coordinates are read at the declared size)"
            )
    frames = keypoints.get("frames")
    if not isinstance(frames, list) or not frames:
        raise CapabilityError(
            "qa.dance_action_events: keypoint input requires a non-empty 'frames' list; "
            "missing keypoint input fails"
        )
    conf_min = float(DEFAULT_THRESHOLDS["joint_confidence_min"])
    normalised: list[dict[str, Any]] = []
    previous_frame: int | None = None
    for entry in frames:
        if not isinstance(entry, dict):
            raise CapabilityError("qa.dance_action_events: every frame entry must be a JSON object")
        frame_no = entry.get("frame")
        if not isinstance(frame_no, int) or isinstance(frame_no, bool) or frame_no < 0:
            raise CapabilityError("qa.dance_action_events: every frame needs a non-negative integer 'frame'")
        if previous_frame is not None and frame_no <= previous_frame:
            raise CapabilityError(
                "qa.dance_action_events: frames must strictly increase; "
                f"got {frame_no} after {previous_frame}"
            )
        previous_frame = frame_no
        expected_t = frame_time(frame_no, fps)
        declared_t = entry.get("t_sec")
        if declared_t is not None:
            if not _is_num(declared_t):
                raise CapabilityError(
                    f"qa.dance_action_events: frame {frame_no} 't_sec' must be numeric"
                )
            if abs(float(declared_t) - expected_t) > 1.0 / fps + 1e-9:
                raise CapabilityError(
                    f"qa.dance_action_events: frame {frame_no} t_sec {float(declared_t):g} "
                    f"disagrees with frame/fps time {expected_t:g}; frame time is "
                    "integer math, never a supplied clock"
                )
        joints = {
            name: _joint(entry, name, frame_no, conf_min) for name in REQUIRED_JOINTS
        }
        normalised.append({"frame": frame_no, "t": expected_t, "joints": joints})
    return {
        "fps": fps,
        "width": float(width),
        "height": float(height),
        "frames": normalised,
        "source": keypoints.get("source", "unspecified"),
        "measurement_basis": keypoints.get("measurement_basis", "offline_keypoints"),
    }


def _confidence(strength: float, threshold: float) -> float:
    if threshold <= 0:
        return 1.0
    return max(0.0, min(1.0, strength / (2.0 * threshold)))


def _dedupe(detections: list[dict[str, Any]], min_separation: int) -> list[dict[str, Any]]:
    """Keep the strongest detection per type within a separation window."""
    kept: list[dict[str, Any]] = []
    for det in sorted(detections, key=lambda d: (-d["strength"], d["frame"])):
        clash = any(
            other["type"] == det["type"]
            and abs(other["frame"] - det["frame"]) <= min_separation
            for other in kept
        )
        if not clash:
            kept.append(det)
    return sorted(kept, key=lambda d: d["frame"])


def _extract_series(validated: dict[str, Any], thresholds: dict[str, float], confidence_floor: float) -> list[dict[str, Any]]:
    frames = validated["frames"]
    window = int(thresholds["peak_window_frames"])
    series: dict[str, list[float]] = {
        "ankle_left_y": [f["joints"]["ankle_left"][1] for f in frames],
        "ankle_right_y": [f["joints"]["ankle_right"][1] for f in frames],
        "wrist_left_y": [f["joints"]["wrist_left"][1] for f in frames],
        "wrist_right_y": [f["joints"]["wrist_right"][1] for f in frames],
        "shoulder_width": [
            abs(f["joints"]["shoulder_right"][0] - f["joints"]["shoulder_left"][0])
            for f in frames
        ],
        "shoulder_y": [
            (f["joints"]["shoulder_left"][1] + f["joints"]["shoulder_right"][1]) / 2.0
            for f in frames
        ],
    }
    detections: list[dict[str, Any]] = []
    n = len(frames)

    def _is_peak(values: list[float], i: int, want_max: bool) -> bool:
        lo, hi = max(0, i - window), min(n, i + window + 1)
        if want_max:
            return all(values[i] >= values[j] for j in range(lo, hi))
        return all(values[i] <= values[j] for j in range(lo, hi))

    def _prominence(values: list[float], i: int, want_max: bool, span: int = 3) -> float:
        lo, hi = max(0, i - span), min(n, i + span + 1)
        if want_max:
            return values[i] - min(min(values[lo:i]) if i > lo else values[i],
                                   min(values[i + 1:hi]) if i + 1 < hi else values[i])
        return max(max(values[lo:i]) if i > lo else values[i],
                   max(values[i + 1:hi]) if i + 1 < hi else values[i]) - values[i]

    # Footsteps: ankle-y local maxima.
    for key in ("ankle_left_y", "ankle_right_y"):
        values = series[key]
        for i in range(n):
            if not _is_peak(values, i, want_max=True):
                continue
            strength = _prominence(values, i, want_max=True)
            slope = values[i] - values[i - 2] if i >= 2 else 0.0
            if strength < 0.5 * thresholds["footstep_min_drop_px"]:
                continue
            if slope < 0.5 * thresholds["footstep_min_slope_px"]:
                continue
            detections.append({
                "type": "footstep", "index": i, "frame": frames[i]["frame"],
                "strength": strength,
                "threshold": thresholds["footstep_min_drop_px"],
                "detail": {"joint": key},
            })
    # Turns: shoulder-width local minima.
    values = series["shoulder_width"]
    for i in range(n):
        if not _is_peak(values, i, want_max=False):
            continue
        strength = _prominence(values, i, want_max=False)
        if strength < 0.5 * thresholds["turn_min_narrow_px"]:
            continue
        detections.append({
            "type": "turn", "index": i, "frame": frames[i]["frame"],
            "strength": strength,
            "threshold": thresholds["turn_min_narrow_px"],
            "detail": {"shoulder_width_px": values[i]},
        })
    # Raise-arm: wrist-y local minima while lifted above the shoulder line.
    for key in ("wrist_left_y", "wrist_right_y"):
        values = series[key]
        for i in range(n):
            if not _is_peak(values, i, want_max=False):
                continue
            lift = series["shoulder_y"][i] - values[i]
            if lift < 0.5 * thresholds["raise_min_lift_px"]:
                continue
            strength = _prominence(values, i, want_max=False)
            if strength < 0.5 * thresholds["raise_min_prominence_px"]:
                continue
            detections.append({
                "type": "raise_arm", "index": i, "frame": frames[i]["frame"],
                "strength": min(strength, lift),
                "threshold": thresholds["raise_min_lift_px"],
                "detail": {"joint": key, "lift_px": lift},
            })
    # Holds: runs of near-zero mean joint speed that follow motion.
    speeds: list[float] = []
    for i in range(1, n):
        total = 0.0
        for name in REQUIRED_JOINTS:
            x0, y0 = frames[i - 1]["joints"][name]
            x1, y1 = frames[i]["joints"][name]
            total += math.hypot(x1 - x0, y1 - y0)
        speeds.append(total / len(REQUIRED_JOINTS))
    min_frames = int(thresholds["hold_min_frames"])
    max_speed = thresholds["hold_max_speed_px_per_frame"]
    i = 0
    while i < len(speeds):
        if speeds[i] < max_speed:
            j = i
            while j < len(speeds) and speeds[j] < max_speed:
                j += 1
            run_frames = j - i + 1
            # Motion must precede the still run (the 3 speeds before it).
            before = speeds[max(0, i - 3):i]
            preceded_by_motion = bool(before) and sum(before) / len(before) >= 2.0 * max_speed
            if run_frames >= min_frames and preceded_by_motion:
                start_index = i + 1  # first still frame (speeds are between frames)
                detections.append({
                    "type": "hold", "index": start_index,
                    "frame": frames[start_index]["frame"],
                    "strength": float(run_frames),
                    "threshold": float(min_frames),
                    "detail": {"run_frames": run_frames},
                })
            i = j
        else:
            i += 1
    deduped = _dedupe(detections, int(thresholds["min_separation_frames"]))
    events: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    for det in deduped:
        confidence = _confidence(det["strength"], det["threshold"])
        record = {
            "type": det["type"],
            "t": frames[det["index"]]["t"],
            "frame": det["frame"],
            "confidence": round(confidence, 4),
            "source": "pose_delta",
            "strength": round(float(det["strength"]), 4),
            "detail": det["detail"],
        }
        if det["strength"] >= det["threshold"] and confidence >= confidence_floor:
            events.append(record)
        else:
            candidates.append(record)
    events.sort(key=lambda e: (e["t"], e["type"]))
    candidates.sort(key=lambda e: (e["t"], e["type"]))
    return events, candidates


def extract_dance_events(
    keypoints: Any,
    *,
    thresholds: Any = None,
    confidence_floor: float = DEFAULT_CONFIDENCE_FLOOR,
) -> dict[str, Any]:
    """Extract dance events from an offline keypoint sequence."""
    if not _is_num(confidence_floor) or not 0.0 < float(confidence_floor) <= 1.0:
        raise CapabilityError("qa.dance_action_events: confidence_floor must be in (0, 1]")
    resolved = _resolve_thresholds(thresholds)
    validated = validate_keypoint_input(keypoints)
    events, candidates = _extract_series(validated, resolved, float(confidence_floor))
    return {
        "verdict": "pass",
        "events": events,
        "candidates": candidates,
        "frames_checked": len(validated["frames"]),
        "fps": validated["fps"],
        "width": validated["width"],
        "height": validated["height"],
        "keypoint_source": validated["source"],
        "measurement_basis": validated["measurement_basis"],
        "human_measured": False,
        "backend": pose_backend_status(),
        "thresholds": resolved,
        "confidence_floor": float(confidence_floor),
    }


def _event_time(event: dict[str, Any], where: str) -> float:
    t = event.get("t")
    if not _is_num(t) or float(t) < 0:
        raise CapabilityError(f"qa.dance_action_events: {where} event needs a numeric t >= 0")
    event_type = event.get("type")
    if event_type not in EVENT_TYPES:
        raise CapabilityError(
            f"qa.dance_action_events: {where} event type {event_type!r} is unknown; "
            f"known: {list(EVENT_TYPES)}"
        )
    return float(t)


def score_events(
    detected: Any,
    ground_truth: Any,
    *,
    tolerance_ms: float = 100.0,
) -> dict[str, Any]:
    """Score detected events against ground-truth annotations.

    Greedy per-type matching in time order: a detection matches
    a truth event of the same type when ``|dt| <= tolerance``.
    Unmatched detections are false positives, unmatched truth
    events are false negatives. Every match records its signed
    error in milliseconds. A low F1 is reported, never raised.
    """
    if not _is_num(tolerance_ms) or float(tolerance_ms) <= 0:
        raise CapabilityError("qa.dance_action_events: tolerance_ms must be > 0")
    tolerance_s = float(tolerance_ms) / 1000.0
    if not isinstance(detected, list) or not isinstance(ground_truth, list):
        raise CapabilityError(
            "qa.dance_action_events: detected and ground_truth must both be lists"
        )
    for where, items in (("detected", detected), ("ground_truth", ground_truth)):
        for item in items:
            if not isinstance(item, dict):
                raise CapabilityError(
                    f"qa.dance_action_events: {where} entries must be JSON objects"
                )
            _event_time(item, where)
    per_type: dict[str, dict[str, Any]] = {}
    all_errors: list[dict[str, Any]] = []
    total_tp = total_fp = total_fn = 0
    for event_type in EVENT_TYPES:
        det = sorted(
            (e for e in detected if e["type"] == event_type),
            key=lambda e: float(e["t"]),
        )
        truth = sorted(
            (e for e in ground_truth if e["type"] == event_type),
            key=lambda e: float(e["t"]),
        )
        used_truth: set[int] = set()
        matches: list[dict[str, Any]] = []
        unmatched_det: list[dict[str, Any]] = []
        for d in det:
            best: int | None = None
            best_err: float | None = None
            for idx, g in enumerate(truth):
                if idx in used_truth:
                    continue
                err = float(d["t"]) - float(g["t"])
                if abs(err) <= tolerance_s and (best_err is None or abs(err) < abs(best_err)):
                    best, best_err = idx, err
            if best is None:
                unmatched_det.append({"type": event_type, "t": float(d["t"])})
            else:
                used_truth.add(best)
                match = {
                    "type": event_type,
                    "detected_t": float(d["t"]),
                    "truth_t": float(truth[best]["t"]),
                    "error_ms": round(float(best_err) * 1000.0, 3),
                }
                matches.append(match)
                all_errors.append(match)
        unmatched_truth = [
            {"type": event_type, "t": float(g["t"])}
            for idx, g in enumerate(truth)
            if idx not in used_truth
        ]
        tp, fp, fn = len(matches), len(unmatched_det), len(unmatched_truth)
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
        per_type[event_type] = {
            "tp": tp, "fp": fp, "fn": fn,
            "precision": round(precision, 4), "recall": round(recall, 4),
            "f1": round(f1, 4),
            "matches": matches,
            "false_positives": unmatched_det,
            "false_negatives": unmatched_truth,
        }
        total_tp, total_fp, total_fn = total_tp + tp, total_fp + fp, total_fn + fn
    precision = total_tp / (total_tp + total_fp) if (total_tp + total_fp) else 0.0
    recall = total_tp / (total_tp + total_fn) if (total_tp + total_fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    errors_ms = [abs(m["error_ms"]) for m in all_errors]
    return {
        "tolerance_ms": float(tolerance_ms),
        "overall": {
            "tp": total_tp, "fp": total_fp, "fn": total_fn,
            "precision": round(precision, 4), "recall": round(recall, 4),
            "f1": round(f1, 4),
            "max_abs_error_ms": max(errors_ms) if errors_ms else None,
            "mean_abs_error_ms": (
                round(sum(errors_ms) / len(errors_ms), 3) if errors_ms else None
            ),
        },
        "per_type": per_type,
        "matches": all_errors,
        "human_measured": False,
    }


def generate_synthetic_dance(
    *,
    fps: int = 10,
    duration_s: float = 4.0,
    width: int = 320,
    height: int = 240,
) -> dict[str, Any]:
    """Generate a code-drawn synthetic dance: frames, keypoints, truth.

    No external video, no human footage, no pose estimator.
    One stick figure moves on a plain background under a fixed
    script; the keypoints below are the exact joint positions
    the drawing uses, so extraction can be scored against the
    script's ground-truth event times. The result is labelled
    ``synthetic_video`` everywhere: it measures the extractor
    against a known script, not against a human dancer.

    Script (fps 10, 40 frames): footstep at 0.5s (left ankle
    dips), raise_arm at 1.2s (right wrist rises), turn at 2.0s
    (shoulder line narrows), hold from 2.8s (all joints still
    after motion), footstep at 3.7s (right ankle dips).
    """
    if not isinstance(fps, int) or isinstance(fps, bool) or fps <= 0:
        raise CapabilityError("qa.dance_action_events: synthetic fps must be a positive integer")
    if not _is_num(duration_s) or float(duration_s) <= 0:
        raise CapabilityError("qa.dance_action_events: synthetic duration_s must be > 0")
    count = max(1, round(float(duration_s) * fps))
    base: dict[str, tuple[float, float]] = {
        "ankle_left": (135.0, 200.0),
        "ankle_right": (185.0, 200.0),
        "wrist_left": (115.0, 130.0),
        "wrist_right": (205.0, 130.0),
        "shoulder_left": (130.0, 110.0),
        "shoulder_right": (190.0, 110.0),
        "hip_left": (135.0, 170.0),
        "hip_right": (185.0, 170.0),
    }
    joints_series: list[dict[str, tuple[float, float]]] = [dict(base) for _ in range(count)]

    def _set(frame: int, name: str, x: float, y: float) -> None:
        if 0 <= frame < count:
            joints_series[frame][name] = (x, y)

    # Footstep 1: left ankle dips, centred on frame 5 (t=0.5).
    for offset, y in zip((-3, -2, -1, 0, 1, 2, 3), (200.0, 204.0, 208.0, 212.0, 208.0, 204.0, 200.0)):
        _set(5 + offset, "ankle_left", 135.0, y)
    # Raise-arm: right wrist rises, centred on frame 12 (t=1.2).
    for offset, y in zip((-3, -2, -1, 0, 1, 2, 3), (130.0, 110.0, 90.0, 70.0, 90.0, 110.0, 130.0)):
        _set(12 + offset, "wrist_right", 205.0, y)
    # Turn: shoulder line narrows, centred on frame 20 (t=2.0).
    for offset, half in zip((-3, -2, -1, 0, 1, 2, 3), (30.0, 24.0, 18.0, 12.5, 18.0, 24.0, 30.0)):
        _set(20 + offset, "shoulder_left", 160.0 - half, 110.0)
        _set(20 + offset, "shoulder_right", 160.0 + half, 110.0)
    # Motion before the hold: both hips bob 20px on frames 24-27
    # (mean joint speed 5.0 px/frame, so the still run that
    # follows is a genuine stop, not a continuation of stillness).
    # Hips are used because no detector reads hip motion, so the
    # bob cannot leak into footstep / turn / raise_arm signals.
    for frame, y in zip((24, 25, 26, 27), (150.0, 170.0, 150.0, 170.0)):
        _set(frame, "hip_left", 135.0, y)
        _set(frame, "hip_right", 185.0, y)
    # Hold: frames 28-34 frozen at the base pose. Frame 27 already
    # ends at the base pose (hips back at 170), so the 27->28
    # transition is still too, and the run starts at frame 28.
    for frame in range(28, 35):
        joints_series[frame] = dict(base)
    # Footstep 2: right ankle dips, centred on frame 37 (t=3.7).
    for offset, y in zip((-3, -2, -1, 0, 1, 2), (200.0, 204.0, 208.0, 212.0, 208.0, 204.0)):
        _set(37 + offset, "ankle_right", 185.0, y)
    frames = [
        {
            "frame": i,
            "t_sec": frame_time(i, fps),
            "joints": {
                name: {"x": pos[0], "y": pos[1], "confidence": 1.0}
                for name, pos in joints_series[i].items()
            },
        }
        for i in range(count)
    ]
    ground_truth = [
        {"type": "footstep", "t": 0.5, "frame": 5, "source": "script"},
        {"type": "raise_arm", "t": 1.2, "frame": 12, "source": "script"},
        {"type": "turn", "t": 2.0, "frame": 20, "source": "script"},
        {"type": "hold", "t": 2.8, "frame": 28, "source": "script"},
        {"type": "footstep", "t": 3.7, "frame": 37, "source": "script"},
    ]
    return {
        "fps": fps,
        "width": width,
        "height": height,
        "frames": frames,
        "ground_truth": ground_truth,
        "source": "synthetic_generator",
        "measurement_basis": "synthetic_video",
        "human_measured": False,
        "script": {
            "description": "code-generated stick-figure dance; no human footage",
            "event_frames": {event["type"]: event["frame"] for event in ground_truth},
        },
    }


def render_synthetic_dance_video(
    synthetic: dict[str, Any],
    out_path: Path,
    *,
    work_dir: Path | None = None,
) -> dict[str, Any]:
    """Draw the synthetic dance as frames and encode an mp4.

    The drawing uses the generator's own joint positions, so
    the video shows exactly the motion the keypoints describe.
    It is synthetic evidence for the extractor, not a dance
    performance: no human, no skeleton-dance product, no
    external footage. Missing ffmpeg/ffprobe raises.
    """
    try:
        from PIL import Image, ImageDraw
    except Exception as exc:  # pragma: no cover - Pillow is a hevi dependency
        raise CapabilityError(f"qa.dance_action_events: Pillow is required: {exc}") from exc
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if ffmpeg is None or ffprobe is None:
        raise CapabilityError("qa.dance_action_events: ffmpeg and ffprobe are required on PATH")
    if not isinstance(synthetic, dict) or not synthetic.get("frames"):
        raise CapabilityError("qa.dance_action_events: synthetic dance needs a non-empty 'frames' list")
    fps = synthetic.get("fps")
    width, height = synthetic.get("width"), synthetic.get("height")
    if not isinstance(fps, int) or fps <= 0 or not width or not height:
        raise CapabilityError("qa.dance_action_events: synthetic dance needs fps/width/height")
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    frames_dir = Path(work_dir) if work_dir is not None else out_path.parent / "synthetic_frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    frame_paths: list[Path] = []
    for entry in synthetic["frames"]:
        joints = {
            name: (point["x"], point["y"])
            for name, point in entry["joints"].items()
        }
        img = Image.new("RGB", (int(width), int(height)), (24, 24, 32))
        draw = ImageDraw.Draw(img)
        draw.line([(0, 212), (int(width), 212)], fill=(90, 90, 110), width=2)
        head = ((joints["shoulder_left"][0] + joints["shoulder_right"][0]) / 2.0,
                (joints["shoulder_left"][1] + joints["shoulder_right"][1]) / 2.0 - 28.0)
        draw.ellipse([head[0] - 12, head[1] - 12, head[0] + 12, head[1] + 12],
                     fill=(240, 200, 120), outline=(20, 20, 20))
        segments = [
            ("shoulder_left", "shoulder_right"),
            ("shoulder_left", "hip_left"),
            ("shoulder_right", "hip_right"),
            ("hip_left", "hip_right"),
            ("shoulder_left", "wrist_left"),
            ("shoulder_right", "wrist_right"),
            ("hip_left", "ankle_left"),
            ("hip_right", "ankle_right"),
        ]
        for a, b in segments:
            draw.line([joints[a], joints[b]], fill=(240, 240, 240), width=5)
        for name, pos in joints.items():
            draw.ellipse([pos[0] - 4, pos[1] - 4, pos[0] + 4, pos[1] + 4],
                         fill=(80, 160, 255))
        path = frames_dir / f"frame_{entry['frame']:06d}.png"
        img.save(path)
        frame_paths.append(path)
    pattern = frames_dir / "frame_%06d.png"
    cmd = [ffmpeg, "-y", "-framerate", str(fps), "-i", str(pattern),
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
           "-pix_fmt", "yuv420p", str(out_path)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 or not out_path.exists() or out_path.stat().st_size == 0:
        raise CapabilityError(
            f"qa.dance_action_events: ffmpeg failed: {(proc.stderr or '')[-500:]}"
        )
    probe = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(out_path)],
        capture_output=True, text=True)
    try:
        actual = float((probe.stdout or "").strip())
    except ValueError as exc:
        raise CapabilityError("qa.dance_action_events: ffprobe could not read the synthetic mp4") from exc
    expected = len(frame_paths) / fps
    if abs(actual - expected) > 0.25:
        raise CapabilityError(
            f"qa.dance_action_events: ffprobe duration {actual}s != frame span {expected}s"
        )
    return {
        "mp4": str(out_path),
        "duration_sec": actual,
        "bytes": out_path.stat().st_size,
        "frame_count": len(frame_paths),
        "fps": fps,
        "sha256": hashlib.sha256(out_path.read_bytes()).hexdigest(),
        "human_measured": False,
        "measurement_basis": "synthetic_video",
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    mode = str(params.get("mode", "extract"))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if mode == "backend":
        report: dict[str, Any] = pose_backend_status()
        ok = True
    elif mode == "score":
        report = score_events(
            params.get("detected"), params.get("ground_truth"),
            tolerance_ms=float(params.get("tolerance_ms", 100.0)),
        )
        ok = True
    elif mode == "synthetic":
        synthetic = generate_synthetic_dance(
            fps=int(params.get("fps", 10)),
            duration_s=float(params.get("duration_s", 4.0)),
            width=int(params.get("width", 320)),
            height=int(params.get("height", 240)),
        )
        extracted = extract_dance_events(
            synthetic, thresholds=params.get("thresholds"),
            confidence_floor=float(params.get("confidence_floor", DEFAULT_CONFIDENCE_FLOOR)),
        )
        scored = score_events(
            extracted["events"], synthetic["ground_truth"],
            tolerance_ms=float(params.get("tolerance_ms", 100.0)),
        )
        report = {
            "measurement_basis": "synthetic_video",
            "human_measured": False,
            "synthetic": {
                "fps": synthetic["fps"], "width": synthetic["width"],
                "height": synthetic["height"],
                "frames": len(synthetic["frames"]),
                "ground_truth": synthetic["ground_truth"],
            },
            "extracted": extracted,
            "score": scored,
        }
        if params.get("render_video"):
            video = render_synthetic_dance_video(
                synthetic, out_dir / "synthetic_dance.mp4",
                work_dir=out_dir / "synthetic_frames",
            )
            report["video"] = video
        ok = scored["overall"]["f1"] == 1.0
    else:
        report = extract_dance_events(
            params.get("keypoints"), thresholds=params.get("thresholds"),
            confidence_floor=float(params.get("confidence_floor", DEFAULT_CONFIDENCE_FLOOR)),
        )
        ok = report["verdict"] == "pass"
    report_path = out_dir / "dance_action_events_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={
            "report_json": str(report_path),
            "verdict": report.get("verdict", "pass" if ok else "fail"),
            "ok": ok,
        },
    )


def register_dance_action_events_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.dance_action_events",
            kind="line",
            aspects=["16:9", "9:16", "1:1"],
            params_schema={
                "type": "object",
                "properties": {
                    "mode": {"type": "string"},
                    "keypoints": {"type": "object"},
                    "thresholds": {"type": "object"},
                    "confidence_floor": {"type": "number"},
                    "detected": {"type": "array"},
                    "ground_truth": {"type": "array"},
                    "tolerance_ms": {"type": "number"},
                    "fps": {"type": "integer"},
                    "duration_s": {"type": "number"},
                    "width": {"type": "integer"},
                    "height": {"type": "integer"},
                    "render_video": {"type": "boolean"},
                },
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Dance action-event extraction (method reconstructed "
                "from an article description; see "
                "CODE_STAGE_MV_ATTRIBUTION.md): footstep / turn / "
                "raise_arm / hold events with timestamps, confidence "
                "and source, extracted by differencing an offline "
                "keypoint contract only. No pose estimator is "
                "installed, no video is read for keypoints, and "
                "missing keypoints fail. Synthetic-video runs are "
                "labelled synthetic_video, never human measurements."
            ),
            line="qa",
        )
    )
    return ["qa.dance_action_events"]


register_dance_action_events_capabilities_once()
