"""Per-frame CPU render budget gate for SCENE3D (SwiftShader).

The handbook is explicit that the right order is "先量 GPU 耗时和绘制调用，量不出
问题就别去动面数" (§04): a scene is admitted on a *measured* per-frame cost, not
on a triangle guess.  On this CPU-only host there is no GPU timer, so the budget
is expressed in wall-clock seconds per rendered frame, measured by the real
renderer and compared against a per-asset-class ceiling.

The gate is pure arithmetic over measured numbers: it never fabricates a pass.
A caller that has no measurement gets :class:`BudgetNotMeasured`, which is a
failure, not a default-allow.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "BudgetExceeded",
    "BudgetNotMeasured",
    "RenderBudget",
    "measure_budget",
    "DEFAULT_BUDGET_S",
]

# Seconds per 1080p frame on SwiftShader.  These are deliberately generous
# ceilings for a preschool shot (which must stay cheap enough to iterate on);
# they are tuned from the R1D production numbers and re-checked by the tests.
DEFAULT_BUDGET_S: dict[str, float] = {
    "planet": 1.2,
    "town": 1.8,
    "playground": 1.8,
    "default": 2.0,
}


class BudgetNotMeasured(RuntimeError):
    """No per-frame measurement was supplied, so no pass can be granted."""


class BudgetExceeded(RuntimeError):
    """A measured per-frame cost exceeded the ceiling for its class."""

    def __init__(self, message: str, *, report: dict[str, Any]) -> None:
        super().__init__(message)
        self.report = report


@dataclass
class RenderBudget:
    """A measured per-frame cost plus the ceiling it must clear."""

    scene_class: str
    frames: int
    total_s: float
    ceiling_s: float
    frame_times_s: list[float] = field(default_factory=list)

    @property
    def per_frame_s(self) -> float:
        return self.total_s / self.frames if self.frames else float("inf")

    @property
    def p95_s(self) -> float:
        if not self.frame_times_s:
            return float("inf")
        ordered = sorted(self.frame_times_s)
        idx = min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))
        return ordered[idx]

    def passed(self) -> bool:
        return self.per_frame_s <= self.ceiling_s

    def as_dict(self) -> dict[str, Any]:
        return {
            "scene_class": self.scene_class,
            "frames": self.frames,
            "total_s": round(self.total_s, 4),
            "per_frame_s": round(self.per_frame_s, 5),
            "p95_s": round(self.p95_s, 5),
            "ceiling_s": self.ceiling_s,
            "passed": self.passed(),
        }


def measure_budget(
    scene_class: str,
    *,
    frames: int,
    total_s: float,
    frame_times_s: list[float] | None = None,
    ceiling_s: float | None = None,
) -> RenderBudget:
    """Build a budget report; call :meth:`RenderBudget.passed` or the gate below."""
    if frames <= 0:
        raise BudgetNotMeasured("frames must be positive to measure a per-frame budget")
    if total_s < 0:
        raise BudgetNotMeasured("total_s must be non-negative")
    ceiling = DEFAULT_BUDGET_S.get(scene_class, DEFAULT_BUDGET_S["default"]) if ceiling_s is None else ceiling_s
    return RenderBudget(
        scene_class=scene_class,
        frames=frames,
        total_s=total_s,
        ceiling_s=ceiling,
        frame_times_s=list(frame_times_s or []),
    )


def enforce_budget(budget: RenderBudget) -> RenderBudget:
    """Return ``budget`` when it passes, else raise :class:`BudgetExceeded`."""
    if not budget.passed():
        raise BudgetExceeded(
            f"scene3d {budget.scene_class}: {budget.per_frame_s:.3f}s/frame exceeds "
            f"{budget.ceiling_s:.3f}s ceiling",
            report=budget.as_dict(),
        )
    return budget
