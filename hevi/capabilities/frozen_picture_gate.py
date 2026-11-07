"""Frozen-picture gate (``qa.frozen_picture_gate``).

Clean-room rewrite of the frozen-picture judgement and
motion-blur settle discipline behind HeyGen's HyperFrames
engine (Apache-2.0; see HYPERFRAMES_ATTRIBUTION.md). No code,
text or configuration from that repository is copied here.
This module judges offline frame records supplied by the
caller; it performs no image processing and no browser capture.
Callers supply per-frame measurements (hash, difference to the
previous frame, blur score, settle state); this gate decides
what those measurements mean.

Two judgements:

* Frozen picture: frames whose difference to the previous frame
  is zero (identical pixels) form frozen runs. A frozen run
  outside a declared frozen range is ``unexpected_frozen``;
  a declared frozen range whose frames keep changing is
  ``frozen_not_frozen``. Frozen runs are reported, never
  silently treated as motion.
* Motion-blur settle: a frame whose blur score is still above
  the threshold when capture is attempted, without settle
  confirmation, is ``pending`` -- it must not be captured yet.
  The gate returns ``verdict: "pending"`` (not pass, not fail)
  for a sequence that still needs settling, and ``fail`` when
  the settle deadline has passed with blur still above
  threshold.

Failure contract: malformed frame records (not a list, entries
not JSON objects, missing ``frame``) raise
:class:`CapabilityError`. Well-formed records return a verdict
with named issues.
"""

from __future__ import annotations

from typing import Any

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    register,
)

_Registered = False

DEFAULT_FROZEN_DIFF = 0.0
DEFAULT_BLUR_THRESHOLD = 0.5


def _issue(code: str, message: str, **extra: Any) -> dict[str, Any]:
    issue: dict[str, Any] = {"code": code, "message": message}
    issue.update(extra)
    return issue


def frame_diff(a: bytes, b: bytes) -> float:
    """Mean absolute per-byte difference between two frame buffers."""
    if not isinstance(a, (bytes, bytearray)) or not isinstance(b, (bytes, bytearray)):
        raise CapabilityError("frame buffers must be bytes")
    if len(a) != len(b):
        raise CapabilityError("frame buffers must have equal length")
    if not a:
        return 0.0
    return sum(abs(x - y) for x, y in zip(a, b)) / len(a)


def _in_ranges(frame: int, ranges: list[tuple[int, int]]) -> bool:
    return any(start <= frame <= end for start, end in ranges)


def check_frozen_picture(
    frames: Any,
    *,
    declared_frozen: Any = None,
    frozen_diff: float = DEFAULT_FROZEN_DIFF,
) -> dict[str, Any]:
    """Judge frozen runs against declared frozen ranges."""
    if not isinstance(frames, list):
        raise CapabilityError("frames must be a list")
    ranges: list[tuple[int, int]] = []
    if declared_frozen is not None:
        if not isinstance(declared_frozen, list):
            raise CapabilityError("declared_frozen must be a list of [start, end] pairs")
        for pair in declared_frozen:
            if not isinstance(pair, (list, tuple)) or len(pair) != 2:
                raise CapabilityError("each declared frozen range must be [start, end]")
            ranges.append((int(pair[0]), int(pair[1])))
    issues: list[dict[str, Any]] = []
    frozen_runs: list[dict[str, Any]] = []
    run_start: int | None = None
    previous: int | None = None
    for entry in frames:
        if not isinstance(entry, dict) or "frame" not in entry:
            raise CapabilityError("each frame entry must be a JSON object with 'frame'")
        frame_no = int(entry["frame"])
        diff = entry.get("diff_to_prev")
        is_frozen = diff is not None and float(diff) <= frozen_diff
        if is_frozen and run_start is None:
            run_start = frame_no
        if not is_frozen and run_start is not None:
            frozen_runs.append({"start": run_start, "end": previous})
            run_start = None
        previous = frame_no
    if run_start is not None:
        frozen_runs.append({"start": run_start, "end": previous})
    for run in frozen_runs:
        if not _in_ranges(run["start"], ranges) and not _in_ranges(run["end"], ranges):
            issues.append(
                _issue(
                    "unexpected_frozen",
                    f"frames {run['start']}..{run['end']} are frozen but "
                    "outside every declared frozen range",
                    start=run["start"],
                    end=run["end"],
                )
            )
    for start, end in ranges:
        changing = [
            int(e["frame"])
            for e in frames
            if isinstance(e, dict)
            and start <= int(e["frame"]) <= end
            and e.get("diff_to_prev") is not None
            and float(e["diff_to_prev"]) > frozen_diff
        ]
        if changing:
            issues.append(
                _issue(
                    "frozen_not_frozen",
                    f"declared frozen range {start}..{end} keeps changing "
                    f"at frames {changing[:5]}",
                    start=start,
                    end=end,
                    frames=changing[:5],
                )
            )
    verdict = "fail" if issues else "pass"
    return {
        "verdict": verdict,
        "frozen_runs": frozen_runs,
        "issues": issues,
    }


def check_blur_settle(
    frames: Any,
    *,
    blur_threshold: float = DEFAULT_BLUR_THRESHOLD,
    settle_deadline_ms: float = 1000.0,
) -> dict[str, Any]:
    """A blurry frame without settle confirmation must not be captured."""
    if not isinstance(frames, list):
        raise CapabilityError("frames must be a list")
    issues: list[dict[str, Any]] = []
    pending_frames: list[int] = []
    for entry in frames:
        if not isinstance(entry, dict) or "frame" not in entry:
            raise CapabilityError("each frame entry must be a JSON object with 'frame'")
        frame_no = int(entry["frame"])
        blur = entry.get("blur_score")
        if blur is None:
            continue
        if float(blur) <= blur_threshold:
            continue
        if entry.get("settled") is True:
            continue
        waited = float(entry.get("waited_ms", 0.0))
        if waited >= settle_deadline_ms:
            issues.append(
                _issue(
                    "blur_not_settled",
                    f"frame {frame_no} blur score {blur} still above "
                    f"threshold {blur_threshold} after {waited}ms "
                    "(deadline exceeded); do not capture",
                    frame=frame_no,
                    blur_score=blur,
                    waited_ms=waited,
                )
            )
        else:
            pending_frames.append(frame_no)
    if issues:
        verdict = "fail"
    elif pending_frames:
        verdict = "pending"
    else:
        verdict = "pass"
    return {
        "verdict": verdict,
        "pending_frames": pending_frames,
        "issues": issues,
    }


def _render(params: dict[str, Any]) -> CapabilityResult:
    mode = params.get("mode", "frozen")
    if mode == "blur":
        result = check_blur_settle(
            params.get("frames"),
            blur_threshold=float(params.get("blur_threshold", DEFAULT_BLUR_THRESHOLD)),
            settle_deadline_ms=float(params.get("settle_deadline_ms", 1000.0)),
        )
    else:
        result = check_frozen_picture(
            params.get("frames"), declared_frozen=params.get("declared_frozen")
        )
    return CapabilityResult(
        ok=result["verdict"] == "pass", output=result, files=[]
    )


def register_frozen_picture_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.frozen_picture_gate",
            kind="line",
            aspects=["16:9", "9:16", "1:1"],
            params_schema={
                "type": "object",
                "properties": {
                    "frames": {},
                    "mode": {"type": "string"},
                    "declared_frozen": {},
                    "blur_threshold": {"type": "number"},
                    "settle_deadline_ms": {"type": "number"},
                },
                "required": ["frames"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Frozen-picture gate (HyperFrames discipline, "
                "clean-room): frozen runs must match declared frozen "
                "ranges, and a frame whose motion blur has not "
                "settled is pending and must not be captured. Judges "
                "offline frame records supplied by the caller; no "
                "image processing, no browser capture."
            ),
            line="qa",
        )
    )
    return ["qa.frozen_picture_gate"]
