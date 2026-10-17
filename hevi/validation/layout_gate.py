"""Generic Layout Quality Gate for Hevi compositions and motion templates.

Extracted and generalized from code-brand-film's layout_audit.mjs.
Performs frame-by-frame spatial analysis across the animation timeline:
  - Text Collision: two visible pieces of text overlapping by > 12% of the smaller box
  - Text Clipped: text cut off by canvas boundaries
  - Safe Area: text penetrating into outer boundary margins (default: 48px)
  - Text Hidden: text occluded by an opaque overlapping shape or container

Supports both DOM-based HTML compositions (GSAP / HyperFrames) and Canvas-based
templates (amtpl draw(t) with fillText recording).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Box:
    """Axis-aligned bounding box."""

    x: float
    y: float
    w: float
    h: float
    text: str = ""
    alpha: float = 1.0
    container: str | None = None

    @property
    def left(self) -> float:
        return self.x

    @property
    def top(self) -> float:
        return self.y

    @property
    def right(self) -> float:
        return self.x + self.w

    @property
    def bottom(self) -> float:
        return self.y + self.h

    @property
    def area(self) -> float:
        return max(0.0, self.w) * max(0.0, self.h)


def compute_intersection(a: Box, b: Box) -> float:
    """Area of intersection between two boxes."""
    dx = max(0.0, min(a.right, b.right) - max(a.left, b.left))
    dy = max(0.0, min(a.bottom, b.bottom) - max(a.top, b.top))
    return dx * dy


def compute_overlap_ratio(a: Box, b: Box) -> float:
    """Overlap ratio relative to the smaller box's area."""
    inter = compute_intersection(a, b)
    if inter <= 0.0:
        return 0.0
    min_area = min(a.area, b.area)
    if min_area <= 0.0:
        return 0.0
    return inter / min_area


def check_safe_area(box: Box, canvas_w: float, canvas_h: float, margin: float = 48.0) -> bool:
    """Return True if box is entirely inside the safe area margin."""
    if box.area <= 0.0:
        return True
    return (
        box.left >= margin
        and box.top >= margin
        and box.right <= (canvas_w - margin)
        and box.bottom <= (canvas_h - margin)
    )


def check_clipped(box: Box, canvas_w: float, canvas_h: float, tolerance: float = 0.97) -> bool:
    """Return True if box is clipped by canvas edge (visible area < tolerance * total area)."""
    if box.area <= 0.0:
        return False
    inter = max(0.0, min(box.right, canvas_w) - max(box.left, 0.0)) * max(
        0.0, min(box.bottom, canvas_h) - max(box.top, 0.0)
    )
    return inter < (box.area * tolerance)


@dataclass
class ProblemRun:
    kind: str
    key: str
    detail: str
    from_t: float
    to_t: float
    duration: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "key": self.key,
            "detail": self.detail,
            "from": round(self.from_t, 3),
            "to": round(self.to_t, 3),
            "duration": round(self.duration, 3),
        }


@dataclass
class LayoutAuditReport:
    canvas_width: int
    canvas_height: int
    duration_s: float
    step_s: float
    min_run_s: float
    problems: list[ProblemRun] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return len(self.problems) == 0

    @property
    def failed_kinds(self) -> list[str]:
        return sorted({p.kind for p in self.problems})

    def summary(self) -> dict[str, Any]:
        kinds = ["text hidden", "text collision", "text clipped", "safe area", "parked off-edge"]
        counts = {k: len([p for p in self.problems if p.kind == k]) for k in kinds}
        return {
            "passed": self.passed,
            "problems_count": len(self.problems),
            "breakdown": counts,
            "failed_kinds": self.failed_kinds,
            "problems": [p.to_dict() for p in self.problems],
        }


def audit_sampled_frames(
    samples: dict[float, list[Box]],
    canvas_w: int,
    canvas_h: int,
    step: float = 0.1,
    min_run: float = 0.3,
    safe_margin: float = 48.0,
    overlap_threshold: float = 0.12,
    min_alpha: float = 0.35,
) -> LayoutAuditReport:
    """Audit recorded text bounding boxes across sampled timeline frames.

    Aggregates momentary violations into continuous temporal runs lasting >= min_run.
    """
    runs: dict[str, dict[str, Any]] = {}
    times = sorted(samples.keys())
    dur = max(times) if times else 0.0

    for t in times:
        boxes = [b for b in samples[t] if b.alpha >= min_alpha and b.area > 4.0]
        # 1. Safe area and clipped
        for b in boxes:
            name = f'"{b.text}"'
            if check_clipped(b, canvas_w, canvas_h):
                k = f"text clipped|{name}"
                runs.setdefault(
                    k,
                    {
                        "kind": "text clipped",
                        "key": name,
                        "detail": f"cut by canvas boundary [{int(b.x)}, {int(b.y)}, {int(b.w)}, {int(b.h)}]",
                        "times": [],
                    },
                )["times"].append(t)
            elif not check_safe_area(b, canvas_w, canvas_h, margin=safe_margin):
                k = f"safe area|{name}"
                runs.setdefault(
                    k,
                    {
                        "kind": "safe area",
                        "key": name,
                        "detail": f"inside {int(safe_margin)}px outer margin [{int(b.x)}, {int(b.y)}, {int(b.w)}, {int(b.h)}]",
                        "times": [],
                    },
                )["times"].append(t)

        # 2. Text collisions (AABB overlap > 12%)
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                a, b = boxes[i], boxes[j]
                if a.text == b.text and abs(a.x - b.x) < 1.0 and abs(a.y - b.y) < 1.0:
                    continue
                ratio = compute_overlap_ratio(a, b)
                if ratio > overlap_threshold:
                    key = f'"{a.text}" x "{b.text}"'
                    k = f"text collision|{key}"
                    runs.setdefault(
                        k,
                        {
                            "kind": "text collision",
                            "key": key,
                            "detail": f"overlap {ratio:.1%} > {overlap_threshold:.0%}",
                            "times": [],
                        },
                    )["times"].append(t)

    # Filter runs lasting >= min_run
    problems: list[ProblemRun] = []
    for r in runs.values():
        t_list = r["times"]
        if not t_list:
            continue
        best = (0.0, 0.0)
        start = prev = t_list[0]
        for t in t_list[1:] + [float("inf")]:
            if t - prev > step * 1.5:
                length = prev - start + step
                if length > (best[1] - best[0]):
                    best = (start, prev + step)
                start = t
            prev = t
        span = best[1] - best[0]
        if span >= (min_run - 1e-5):
            problems.append(
                ProblemRun(
                    kind=r["kind"],
                    key=r["key"],
                    detail=r["detail"],
                    from_t=best[0],
                    to_t=best[1],
                    duration=span,
                )
            )

    problems.sort(key=lambda p: (p.from_t, p.kind))
    return LayoutAuditReport(
        canvas_width=canvas_w,
        canvas_height=canvas_h,
        duration_s=dur,
        step_s=step,
        min_run_s=min_run,
        problems=problems,
    )
