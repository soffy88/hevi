"""SCENE3D quality gates: kids gate + layout (safe-area framing) gate.

The task requires the scene templates to be chained through the kids-content
gate and a layout gate before a shot counts as good.  Both gates are pure
functions over real measurements — an unreadable frame or a missing subject is a
failure, never a pass.

* **kids gate** — the existing :mod:`hevi.layer4_legacy.scene3d.kids_gate`
  (no fast flicker, slow pacing, bounded saturation) over decoded frames.
* **layout gate** — the subject (character / hero object) must sit inside the
  10% top/bottom, 5% left/right safe area at every sampled time, so a preschool
  viewer never sees the subject cropped by the frame edge.

``run_scene_gates`` is the single entry point the capability layer calls; it
returns a structured report and never fabricates a pass.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .kids_gate import extract_frames, evaluate_frames

__all__ = [
    "LayoutGateReport",
    "SceneGateReport",
    "run_layout_gate",
    "run_scene_gates",
    "SAFE_AREA",
]

# (left, right, top, bottom) margins as fractions of the frame.
SAFE_AREA = {"left": 0.05, "right": 0.05, "top": 0.10, "bottom": 0.10}


@dataclass
class LayoutGateReport:
    """Whether the subject stays inside the safe area at every sampled time."""

    passed: bool
    samples: int
    boxes: list[dict[str, Any]] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "samples": self.samples,
            "safe_area": dict(SAFE_AREA),
            "boxes": list(self.boxes),
            "failures": list(self.failures),
        }


def run_layout_gate(boxes: list[dict[str, Any] | None]) -> LayoutGateReport:
    """Check subject screen bboxes against the safe area.

    ``boxes`` are the outputs of ``SceneRenderer.probe_subject_bboxes`` /
    ``probe_character_bbox`` — normalised x0/y0/x1/y1 with y measured from the
    top.  A ``None`` box means no subject was in frame, which is a failure.
    """
    failures: list[str] = []
    clean: list[dict[str, Any]] = []
    for i, b in enumerate(boxes):
        if b is None:
            failures.append(f"sample {i}: no subject in frame")
            continue
        clean.append(dict(b))
        if b["x0"] < SAFE_AREA["left"] - 1e-6:
            failures.append(f"sample {i}: left crop x0={b['x0']:.3f}")
        if b["x1"] > 1.0 - SAFE_AREA["right"] + 1e-6:
            failures.append(f"sample {i}: right crop x1={b['x1']:.3f}")
        if b["y0"] < SAFE_AREA["top"] - 1e-6:
            failures.append(f"sample {i}: top crop y0={b['y0']:.3f}")
        if b["y1"] > 1.0 - SAFE_AREA["bottom"] + 1e-6:
            failures.append(f"sample {i}: bottom crop y1={b['y1']:.3f}")
    return LayoutGateReport(
        passed=not failures, samples=len(boxes), boxes=clean, failures=failures
    )


@dataclass
class SceneGateReport:
    """Combined kids + layout gate outcome for one rendered shot."""

    passed: bool
    kids: dict[str, Any]
    layout: dict[str, Any]
    failures: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "kids": self.kids,
            "layout": self.layout,
            "failures": list(self.failures),
        }


def run_scene_gates(
    video: str | Path,
    *,
    fps: float,
    duration_s: float,
    boxes: list[dict[str, Any] | None],
    frame_dir: str | Path,
    frame_samples: int = 24,
) -> SceneGateReport:
    """Run the kids gate on decoded frames and the layout gate on ``boxes``.

    Raises nothing on a failed gate — the caller decides — but an ffmpeg decode
    failure or an empty frame set propagates as an error rather than a pass.
    """
    frames = extract_frames(video, fps=fps, count=frame_samples, out_dir=frame_dir)
    if not frames:
        raise RuntimeError(f"kids gate: no frames decoded from {video}")
    kids = evaluate_frames(frames, fps=fps, duration_s=duration_s)
    layout = run_layout_gate(boxes)
    failures: list[str] = []
    if not kids.passed:
        failures.extend(f"kids: {f}" for f in kids.failures)
    if not layout.passed:
        failures.extend(f"layout: {f}" for f in layout.failures)
    return SceneGateReport(
        passed=not failures,
        kids=kids.as_dict(),
        layout=layout.as_dict(),
        failures=failures,
    )
