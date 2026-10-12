"""质量分量归一化 —— 把量出来的数字折成 0..1 分(纯算法, 零 I/O)。

每个分量有自己的"多少算好"标尺。标尺本身写死在这里并公开, 因为一个不看标尺的
0..1 分数没有意义: 观众/流水线要能问"0.62 是怎么来的"。

量不到的分量返回 ``None``, 调用方负责把它从权重里剔除并显式报"未量测"。
**绝不用 0 顶替** —— 0 在这里表示"这一维完全糟", 而不是"这一维没量"。
"""

from __future__ import annotations

#: 曝光理想中心(0-255)。偏离中心越远扣分越多。
EXPOSURE_TARGET = 128.0
#: 曝光满分容差: 偏离目标这么多仍算满分。
EXPOSURE_TOLERANCE = 48.0
#: 对比度满分所需的标准差(luma stdev)。
CONTRAST_FULL = 64.0
#: 运动满分所需的帧间 luma 差。
MOTION_FULL = 8.0


def aggregate_score(dimension: str, value: float | None) -> float | None:
    """Normalise one measured dimension to 0..1, or None when unmeasured."""
    if value is None:
        return None
    if dimension == "exposure":
        deviation = abs(float(value) - EXPOSURE_TARGET)
        if deviation <= EXPOSURE_TOLERANCE:
            return 1.0
        span = float(EXPOSURE_TOLERANCE) * 2.0
        return max(0.0, round(1.0 - (deviation - EXPOSURE_TOLERANCE) / span, 4))
    if dimension == "contrast":
        return max(0.0, round(min(float(value) / CONTRAST_FULL, 1.0), 4))
    if dimension == "motion":
        return max(0.0, round(min(float(value) / MOTION_FULL, 1.0), 4))
    raise ValueError(f"unknown quality dimension: {dimension!r}")


#: 公开标尺, 报告里原样输出, 让分数可复核。
RULERS = {
    "exposure": {
        "target_luma": EXPOSURE_TARGET,
        "tolerance_luma": EXPOSURE_TOLERANCE,
        "formula": "1 - max(0, |luma - 128| - 48) / 96",
    },
    "contrast": {
        "full_score_stdev": CONTRAST_FULL,
        "formula": "min(luma_stdev / 64, 1)",
    },
    "motion": {
        "full_score_delta": MOTION_FULL,
        "formula": "min(interframe_luma_delta / 8, 1)",
    },
}


__all__ = ["RULERS", "aggregate_score"]
