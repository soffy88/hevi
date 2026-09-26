"""HEVI P4 — DurationController: plan narration budgets to hit duration targets."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class DurationPlan:
    target_s: float
    chars_per_s: float = 10.9
    sentences_per_segment: int = 4
    chars_per_segment: float = 440.0


@dataclass
class DurationReport:
    target_s: float
    estimated_s: float = 0.0
    actual_s: float = 0.0
    error_ratio: float = 0.0
    within_tolerance: bool = False


class DurationController:
    """Plans character budgets from calibrated speech rate, then measures error."""

    def __init__(self, chars_per_s: float = 10.9, tolerance: float = 0.15) -> None:
        self.chars_per_s = chars_per_s
        self.tolerance = tolerance

    def plan(self, target_s: float) -> DurationPlan:
        chars = target_s * self.chars_per_s
        segs = max(1, round(chars / 440.0))
        return DurationPlan(target_s=target_s, chars_per_s=self.chars_per_s,
                            chars_per_segment=chars / segs)

    def estimate(self, narration: str, plan: DurationPlan | None = None) -> float:
        rate = (plan.chars_per_s if plan else self.chars_per_s) or 10.9
        return len(narration) / rate

    def report(self, target_s: float, actual_s: float) -> DurationReport:
        err = abs(actual_s - target_s) / target_s if target_s > 0 else 1.0
        return DurationReport(target_s=target_s, actual_s=actual_s,
                              error_ratio=round(err, 4), within_tolerance=err <= self.tolerance)

    def split_budget(self, narration: str, parts: int) -> list[str]:
        sents = [s.strip() for s in narration.replace("。", ".").split(".") if s.strip()]
        if not sents:
            return [narration]
        base, extra = divmod(len(sents), max(1, parts))
        groups: list[list[str]] = []
        idx = 0
        for p in range(max(1, parts)):
            size = base + (1 if p < extra else 0)
            groups.append(sents[idx:idx + size])
            idx += size
        return [". ".join(g) + ("" if not g else ".") for g in groups if g]


__all__ = ["DurationController", "DurationPlan", "DurationReport"]
