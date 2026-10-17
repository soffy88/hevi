"""色彩分级 / 调色预设（扩展 edit_render._grade_to_vf）。

对标 video-use 的 ASC CDL 风格 + per-segment 调色能力：
  - 丰富预设库（warm_cinematic, neutral_punch, teal_orange, desaturated,
    vintage, high_contrast, cool_blue, golden_hour, noir, pastel）
  - ASC CDL 参数（slope/offset/power/saturation）
  - 自定义 FFmpeg 滤镜链
  - per-segment 调色（每段可用不同 grade）
  - 预设组合（多个预设叠加）
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ── ASC CDL 参数 ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class ASCCDL:
    """ASC CDL 色彩校正参数（对标行业标准）。

    slope: RGB 乘法因子（>1 增亮, <1 减暗）
    offset: RGB 加法偏移
    power: gamma 校正
    saturation: 饱和度（0=灰度, 1=原始）
    """

    slope: tuple[float, float, float] = (1.0, 1.0, 1.0)
    offset: tuple[float, float, float] = (0.0, 0.0, 0.0)
    power: tuple[float, float, float] = (1.0, 1.0, 1.0)
    saturation: float = 1.0

    def to_vf(self) -> str:
        """转为 FFmpeg eq + colorbalance 滤镜链。"""
        parts: list[str] = []

        # eq: brightness ≈ offset 均值, contrast ≈ slope 均值, saturation
        avg_offset = sum(self.offset) / 3
        avg_slope = sum(self.slope) / 3
        if abs(avg_offset) > 0.001:
            parts.append(f"eq=brightness={avg_offset:.4f}")
        if abs(avg_slope - 1.0) > 0.001:
            parts.append(f"eq=contrast={avg_slope:.4f}")
        if abs(self.saturation - 1.0) > 0.001:
            parts.append(f"eq=saturation={self.saturation:.4f}")

        # colorbalance: slope 差异映射到 shadows/midtones/highlights
        rs = (self.slope[0] - 1.0) * 0.5
        gs = (self.slope[1] - 1.0) * 0.5
        bs = (self.slope[2] - 1.0) * 0.5
        if abs(rs) > 0.001 or abs(gs) > 0.001 or abs(bs) > 0.001:
            parts.append(f"colorbalance=rs={rs:.4f}:gs={gs:.4f}:bs={bs:.4f}")

        return ",".join(parts) if parts else "null"


# ── 调色预设 ──────────────────────────────────────────────────────────

GRADE_PRESETS: dict[str, str] = {
    # 原始两个（保持兼容）
    "warm_cinematic": (
        "eq=brightness=0.02:saturation=0.9,"
        "colorbalance=rs=0.08:gs=0.02:bs=-0.05"
    ),
    "neutral_punch": "eq=contrast=1.08:saturation=1.05",

    # 扩展预设
    "teal_orange": (
        "eq=saturation=1.1:contrast=1.05,"
        "colorbalance=rs=0.06:gs=-0.02:bs=-0.08:rh=0.02:gh=0.01:bh=0.04"
    ),
    "desaturated": "eq=saturation=0.6:contrast=1.03:brightness=-0.01",
    "vintage": (
        "eq=saturation=0.75:contrast=0.95:brightness=0.02,"
        "colorbalance=rs=0.05:gs=0.03:bs=-0.02"
    ),
    "high_contrast": "eq=contrast=1.2:saturation=1.1:brightness=-0.02",
    "cool_blue": (
        "eq=saturation=0.9,"
        "colorbalance=rs=-0.05:gs=-0.02:bs=0.08:rm=-0.02:bm=0.04"
    ),
    "golden_hour": (
        "eq=brightness=0.03:saturation=1.1,"
        "colorbalance=rs=0.12:gs=0.05:bs=-0.08"
    ),
    "noir": "eq=saturation=0.0:contrast=1.3:brightness=-0.03",
    "pastel": "eq=saturation=0.7:brightness=0.05:contrast=0.95",
    "bleach_bypass": (
        "eq=saturation=0.5:contrast=1.15:brightness=-0.01,"
        "colorbalance=rs=0.02:gs=0.02:bs=0.02"
    ),
}


# ── per-segment 调色 ──────────────────────────────────────────────────


@dataclass
class SegmentGrade:
    """单段调色指令。"""

    range_index: int
    grade: str  # 预设名 或 自定义 vf 表达式
    cdl: ASCCDL | None = None

    def resolve_vf(self) -> str | None:
        """解析为 FFmpeg 滤镜链。"""
        if self.cdl:
            return self.cdl.to_vf()
        return resolve_grade(self.grade)


@dataclass
class GradePipeline:
    """per-segment 调色管线。"""

    default_grade: str = "none"
    segment_grades: list[SegmentGrade] = field(default_factory=list)

    def get_grade_for_segment(self, index: int) -> str | None:
        """获取第 index 段的调色滤镜。"""
        for sg in self.segment_grades:
            if sg.range_index == index:
                return sg.resolve_vf()
        return resolve_grade(self.default_grade)

    def to_dict(self) -> dict[str, Any]:
        return {
            "default_grade": self.default_grade,
            "segment_grades": [
                {
                    "range_index": sg.range_index,
                    "grade": sg.grade,
                    "cdl": {
                        "slope": list(sg.cdl.slope),
                        "offset": list(sg.cdl.offset),
                        "power": list(sg.cdl.power),
                        "saturation": sg.cdl.saturation,
                    } if sg.cdl else None,
                }
                for sg in self.segment_grades
            ],
        }


# ── 核心解析函数 ──────────────────────────────────────────────────────


def resolve_grade(grade: str) -> str | None:
    """将 grade 名解析为 FFmpeg 滤镜链。

    支持：
      - "none" / "" → None
      - 预设名 → 查 GRADE_PRESETS
      - 含 "=" 的自定义表达式 → 直接使用
      - 逗号分隔的多个预设 → 叠加
    """
    if not grade or grade in ("none", "null"):
        return None

    # 单个预设
    if grade in GRADE_PRESETS:
        return GRADE_PRESETS[grade]

    # 自定义 vf 表达式
    if "=" in grade and "," in grade:
        return grade

    # 多预设叠加（逗号分隔预设名）
    if "," in grade:
        parts = [p.strip() for p in grade.split(",")]
        resolved = []
        for p in parts:
            if p in GRADE_PRESETS:
                resolved.append(GRADE_PRESETS[p])
            elif "=" in p:
                resolved.append(p)
        if resolved:
            return ",".join(resolved)

    return None


def list_presets() -> list[str]:
    """列出所有可用预设名。"""
    return sorted(GRADE_PRESETS.keys())


def build_grade_filter(
    grade: str,
    *,
    preview: bool = False,
    extra_filters: list[str] | None = None,
) -> str | None:
    """构建完整调色滤镜链（可选预览缩放 + 额外滤镜）。"""
    vf_parts: list[str] = []

    if preview:
        vf_parts.append("scale=1280:-2")

    grade_vf = resolve_grade(grade)
    if grade_vf:
        vf_parts.append(grade_vf)

    if extra_filters:
        vf_parts.extend(extra_filters)

    return ",".join(vf_parts) if vf_parts else None
