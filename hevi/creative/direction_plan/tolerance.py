"""Q6:容差标定。用真实流水线的 declared-vs-observed 偏差分布算建议边界。

默认(SYNC_NORMAL ±2 帧、EVENT_LOOSE ±250ms)只是工程起点;本模块让"重新标定"
成为可执行动作,但**不自动改默认**——标定结果需显式采纳(apply_calibration)。
"""

from __future__ import annotations

from dataclasses import dataclass

from hevi.creative.direction_plan.errors import PlanValidationError

CLASSES = ("SYNC_STRICT", "SYNC_NORMAL", "EVENT_LOOSE")
DEFAULT_TOLERANCE_MS = {"SYNC_STRICT": 125, "SYNC_NORMAL": 0, "EVENT_LOOSE": 250}


def default_tolerance_ms(tolerance_class: str, fps: int) -> int:
    """SYNC_NORMAL 的默认是 2 帧,且容差下限永远不小于 1 帧。"""
    if tolerance_class not in CLASSES:
        raise PlanValidationError(f"unknown tolerance class: {tolerance_class}",
                                  code="TOLERANCE_BAD_CLASS")
    if tolerance_class == "SYNC_NORMAL":
        return max(round(2000 / fps), round(1000 / fps))
    return DEFAULT_TOLERANCE_MS[tolerance_class]


@dataclass(frozen=True)
class ToleranceCalibration:
    tolerance_class: str
    sample_count: int
    p50_ms: int
    p95_ms: int
    proposed_ms: int
    floor_ms: int

    def apply(self, current_ms: int) -> int:
        """显式采纳:不小于 1 帧下限,也不低于当前值(只放宽需人工确认语义)。"""
        return max(self.proposed_ms, self.floor_ms, current_ms if current_ms == 0 else 0)


def calibrate(tolerance_class: str, deviations_ms: list[int], *, fps: int,
              percentile: float = 0.95) -> ToleranceCalibration:
    """deviations_ms: |declared - observed| 样本。样本不足 → 拒绝(不猜)。"""
    if not deviations_ms:
        raise PlanValidationError("calibration needs samples", code="TOLERANCE_NO_SAMPLES")
    if len(deviations_ms) < 5:
        raise PlanValidationError(f"calibration needs >=5 samples, got {len(deviations_ms)}",
                                  code="TOLERANCE_TOO_FEW_SAMPLES")
    floor = round(1000 / fps)
    ordered = sorted(deviations_ms)
    p50 = ordered[len(ordered) // 2]
    index = min(len(ordered) - 1, int(round(percentile * (len(ordered) - 1))))
    p95 = ordered[index]
    return ToleranceCalibration(tolerance_class, len(ordered), p50, p95, p95, floor)