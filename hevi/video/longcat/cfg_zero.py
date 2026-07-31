"""CFG-Zero 引导优化 — LongCat-Video optimized_scale 机制适配。

LongCat-Video 在 denoising loop 中使用 CFG-Zero 替代固定 guidance_scale:
  标准 CFG:  noise = uncond + scale * (cond - uncond)
  CFG-Zero:  st_star = dot(cond, uncond) / (||uncond||^2 + eps)
             noise   = uncond * st_star + scale * (cond - uncond * st_star)

核心收益:每步自适应引导强度,避免固定 scale 导致的过饱和/欠饱和。
对 Hevi 的价值:
  - 本地模型(wan_local):直接接入 denoising loop
  - 云端模型:作为 guidance_scale 推荐值的计算工具(后处理分析)
  - prompt 工程:cfg_zero 思路可用于 LLM prompt 的"正面/负面权重"平衡

LongCat 原始代码(pipeline_longcat_video.py,denoising loop):
  positive = noise_pred_cond.reshape(B, -1)
  negative = noise_pred_uncond.reshape(B, -1)
  st_star = dot(positive, negative) / (squared_norm(negative) + 1e-8)
  noise = uncond * st_star + guidance_scale * (cond - uncond * st_star)
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

__all__ = [
    "cfg_zero_scale",
    "apply_cfg_zero",
    "GuidanceTracker",
    "GuidanceStats",
    "GuidanceConfig",
    "recommend_guidance_scale",
    "cfg_zero_noise_combine",
]

_EPS = 1e-8  # 与 LongCat 原始代码一致的 epsilon


def cfg_zero_scale(
    cond_noise: list[float],
    uncond_noise: list[float],
) -> float:
    """计算 CFG-Zero 自适应引导强度 st_star。

    st_star = dot(cond, uncond) / (||uncond||^2 + eps)

    输入为展平的噪声预测向量(可以是 list 或任意可迭代)。

    数学解释:
      st_star 是 uncond 在 cond 方向上的投影系数。
      当 cond 和 uncond 方向一致时 st_star ≈ 1(弱引导);
      当 cond 和 uncond 正交时 st_star ≈ 0(强引导);
      当 cond 和 uncond 反向时 st_star < 0(超强调)。
    """
    if len(cond_noise) != len(uncond_noise):
        raise ValueError(
            f"cond_noise ({len(cond_noise)}) 和 uncond_noise ({len(uncond_noise)}) 长度不匹配"
        )
    if not cond_noise:
        return 1.0

    dot = sum(c * u for c, u in zip(cond_noise, uncond_noise))
    sq_norm = sum(u * u for u in uncond_noise)

    return dot / (sq_norm + _EPS)


def apply_cfg_zero(
    cond_noise: list[float],
    uncond_noise: list[float],
    guidance_scale: float = 4.0,
) -> list[float]:
    """用 CFG-Zero 合并条件/非条件噪声预测。

    标准 CFG: result = uncond + scale * (cond - uncond)
    CFG-Zero: result = uncond * st_star + scale * (cond - uncond * st_star)

    Returns:
        合并后的噪声向量(与输入同长度)。
    """
    st_star = cfg_zero_scale(cond_noise, uncond_noise)

    result = []
    for c, u in zip(cond_noise, uncond_noise):
        # CFG-Zero formula
        combined = u * st_star + guidance_scale * (c - u * st_star)
        result.append(combined)

    return result


def cfg_zero_noise_combine(
    cond_noise: list[float],
    uncond_noise: list[float],
    guidance_scale: float = 4.0,
    use_cfg_zero: bool = True,
) -> list[float]:
    """统一入口:选择标准 CFG 或 CFG-Zero 合并。

    use_cfg_zero=True → apply_cfg_zero (LongCat 模式)
    use_cfg_zero=False → 标准 CFG: uncond + scale * (cond - uncond)
    """
    if not use_cfg_zero:
        return [
            u + guidance_scale * (c - u)
            for c, u in zip(cond_noise, uncond_noise)
        ]
    return apply_cfg_zero(cond_noise, uncond_noise, guidance_scale)


@dataclass(frozen=True)
class GuidanceStats:
    """单步引导统计。"""

    step: int
    st_star: float
    guidance_scale: float
    cond_norm: float
    uncond_norm: float
    angle_degrees: float  # cond/uncond 夹角(度)

    @property
    def guidance_strength(self) -> str:
        """引导强度文本标签。"""
        if self.st_star > 0.8:
            return "weak"   # cond/uncond 同向,引导弱
        if self.st_star > 0.3:
            return "moderate"
        if self.st_star > 0.0:
            return "strong"
        return "extreme"    # 反向,罕见


@dataclass
class GuidanceTracker:
    """多步引导追踪器。

    记录每步的 st_star 值,用于分析引导质量趋势。
    """

    _history: list[GuidanceStats] = field(default_factory=list)

    def record(
        self,
        step: int,
        cond_noise: list[float],
        uncond_noise: list[float],
        guidance_scale: float = 4.0,
    ) -> GuidanceStats:
        """记录一步的引导统计。"""
        st_star = cfg_zero_scale(cond_noise, uncond_noise)

        # 计算范数和夹角
        cond_norm = math.sqrt(sum(c * c for c in cond_noise))
        uncond_norm = math.sqrt(sum(u * u for u in uncond_noise))
        dot = sum(c * u for c, u in zip(cond_noise, uncond_noise))
        cos_angle = dot / max(cond_norm * uncond_norm, _EPS)
        cos_angle = max(-1.0, min(1.0, cos_angle))
        angle = math.degrees(math.acos(cos_angle))

        stats = GuidanceStats(
            step=step,
            st_star=st_star,
            guidance_scale=guidance_scale,
            cond_norm=cond_norm,
            uncond_norm=uncond_norm,
            angle_degrees=angle,
        )
        self._history.append(stats)
        return stats

    @property
    def history(self) -> list[GuidanceStats]:
        return list(self._history)

    @property
    def mean_st_star(self) -> float:
        if not self._history:
            return 0.0
        return sum(s.st_star for s in self._history) / len(self._history)

    @property
    def mean_angle(self) -> float:
        if not self._history:
            return 0.0
        return sum(s.angle_degrees for s in self._history) / len(self._history)

    def summary(self) -> dict[str, Any]:
        """汇总引导质量。"""
        if not self._history:
            return {"steps": 0, "mean_st_star": 0.0, "mean_angle": 0.0}

        st_values = [s.st_star for s in self._history]
        return {
            "steps": len(self._history),
            "mean_st_star": self.mean_st_star,
            "min_st_star": min(st_values),
            "max_st_star": max(st_values),
            "mean_angle": self.mean_angle,
            "strengths": [s.guidance_strength for s in self._history],
        }


@dataclass(frozen=True)
class GuidanceConfig:
    """引导配置(推荐参数,可传给 gen_fn 或 API 调用)。"""

    use_cfg_zero: bool = True
    guidance_scale: float = 4.0
    # CFG-Zero 安全边界:st_star 超出此范围时 clip 到边界
    st_star_min: float = -2.0
    st_star_max: float = 2.0
    # 动态 scale 衰减:后期步数降低 guidance_scale(减少过拟合)
    scale_decay_start_step: int | None = None
    scale_decay_factor: float = 0.95

    def effective_scale(self, step: int) -> float:
        """考虑衰减后的有效 guidance_scale。"""
        if self.scale_decay_start_step is None:
            return self.guidance_scale
        if step < self.scale_decay_start_step:
            return self.guidance_scale
        decay_steps = step - self.scale_decay_start_step
        return self.guidance_scale * (self.scale_decay_factor ** decay_steps)


def recommend_guidance_scale(
    st_star_history: list[float] | None = None,
    current_scale: float = 4.0,
    target_quality: str = "balanced",
) -> float:
    """基于 CFG-Zero 统计推荐 guidance_scale。

    Args:
        st_star_history: 历史 st_star 值列表(来自 GuidanceTracker)
        current_scale: 当前使用的 guidance_scale
        target_quality: 目标质量("balanced" / "high_adherence" / "creative")

    Returns:
        推荐的 guidance_scale 值。
    """
    if st_star_history is None or not st_star_history:
        # 无历史数据,返回经验默认值
        defaults = {
            "balanced": 4.0,
            "high_adherence": 6.0,
            "creative": 2.5,
        }
        return defaults.get(target_quality, 4.0)

    mean_st = sum(st_star_history) / len(st_star_history)

    # mean_st_star 高 → cond/uncond 同向 → 需要更强引导
    # mean_st_star 低 → cond/uncond 差异大 → 可以弱化引导
    if target_quality == "high_adherence":
        if mean_st > 0.6:
            return current_scale * 1.3  # 同向,加强引导
        return current_scale * 0.9

    if target_quality == "creative":
        if mean_st < 0.3:
            return current_scale * 0.7  # 差异大,放松引导
        return current_scale * 0.85

    # balanced
    if mean_st > 0.7:
        return current_scale * 1.15
    if mean_st < 0.2:
        return current_scale * 0.85
    return current_scale
