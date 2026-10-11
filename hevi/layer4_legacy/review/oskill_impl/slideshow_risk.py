"""幻灯片风险评分 —— 合成前的纯算法前门(oskill 边界, 零 I/O)。

对标 OpenMontage 的 slideshow 判红思路(只读设计参考, 本文件为自写实现):
一条片子被判"幻灯片"不是因为它有静帧, 而是因为它**同时**具备四件事:

  1. 重复度高  —— 相邻/整体镜头画面几乎一样(感知哈希汉明距离小)
  2. 静态占比高 —— 画面内几乎没有运动(帧间像素差小)
  3. 运动弱    —— 镜头与镜头之间没有变化(切点前后差异小)
  4. 文字依赖高 —— 时长占比高的镜头靠字幕/文字板撑住, 没有文字就空了

四个分量各自 0..1(越大越像幻灯片), 加权合成 risk 0..1, 超过阈值判红。
所有输入都是**量出来的数字**(perceptual hash / 帧差 / 文字行数), 不是声明;
调用方给不出某项数字时该分量留 None 并显式从权重里剔除, 绝不当 0 算
(0 = "完全不像幻灯片", 会让没测到的维度悄悄放行)。

纯函数: 不解码、不落盘、不调 ffmpeg。可单测、可在合成前干跑。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

#: 权重(分量名 -> 权重)。调用方缺失的分量会被重新归一化。
DEFAULT_WEIGHTS: dict[str, float] = {
    "repeat": 0.25,
    "static": 0.30,
    "weak_motion": 0.25,
    "text_dependent": 0.20,
}

#: 判红阈值与判黄(警告)阈值。
DEFAULT_THRESHOLDS: dict[str, float] = {
    "red": 0.45,
    "amber": 0.30,
}

#: 各分量判"这一维就够糟"的阈值, 用于写人话理由。
_COMPONENT_BAD = 0.60

_COMPONENT_LABELS = {
    "repeat": "重复度",
    "static": "静态占比",
    "weak_motion": "运动强度",
    "text_dependent": "文字依赖",
}


@dataclass(frozen=True)
class SlideshowRisk:
    """一次幻灯片风险评分的结果(不可变)。"""

    risk: float
    verdict: str  # "red" | "amber" | "green"
    components: dict[str, float] = field(default_factory=dict)
    measured: dict[str, float] = field(default_factory=dict)
    missing: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    weights: dict[str, float] = field(default_factory=dict)

    @property
    def is_red(self) -> bool:
        return self.verdict == "red"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["is_red"] = self.is_red
        return data


def _clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else float(x)


def similarity_to_repeat(similarity: float) -> float:
    """镜头一致性/相似度(0..1, 越高越像) → 重复度(0..1, 越高越糟)。

    OpenMontage 风格的一致性打分是"越高越连贯"; 幻灯片风险要的是反面:
    一致=没换画面=重复。所以这里取 1 - similarity。
    """
    return _clamp01(1.0 - _clamp01(similarity))


def score_slideshow_risk(
    *,
    repeat: float | None = None,
    static: float | None = None,
    weak_motion: float | None = None,
    text_dependent: float | None = None,
    weights: dict[str, float] | None = None,
    thresholds: dict[str, float] | None = None,
) -> SlideshowRisk:
    """把四个已量测分量合成为风险分。

    任何分量为 None 表示"这一维没测", 不参与加权(不是 0 分)。
    四个分量全缺 → 返回 risk=0 但 verdict="unknown"(不能判绿放行)。
    """
    w = dict(DEFAULT_WEIGHTS)
    if weights:
        for key, value in weights.items():
            if key in w:
                w[key] = float(value)
    th = dict(DEFAULT_THRESHOLDS)
    if thresholds:
        th.update({k: float(v) for k, v in thresholds.items() if k in th})

    raw = {
        "repeat": repeat,
        "static": static,
        "weak_motion": weak_motion,
        "text_dependent": text_dependent,
    }
    present = {k: _clamp01(v) for k, v in raw.items() if v is not None}
    missing = tuple(k for k, v in raw.items() if v is None)

    if not present:
        return SlideshowRisk(
            risk=0.0,
            verdict="unknown",
            components={},
            measured={},
            missing=missing,
            reasons=("四个风险分量都没量测, 不给结论",),
            weights=w,
        )

    total_w = sum(w[k] for k in present)
    risk = sum(present[k] * w[k] for k in present) / total_w if total_w else 0.0
    risk = _clamp01(risk)

    if risk >= th["red"]:
        verdict = "red"
    elif risk >= th["amber"]:
        verdict = "amber"
    else:
        verdict = "green"

    reasons: list[str] = []
    for key, value in sorted(present.items(), key=lambda kv: kv[1] * w[kv[0]], reverse=True):
        if value >= _COMPONENT_BAD:
            reasons.append(f"{_COMPONENT_LABELS.get(key, key)}分量 {value:.2f} 超标")
    if missing:
        reasons.append("未量测(不计分): " + ", ".join(_COMPONENT_LABELS.get(k, k) for k in missing))
    if not reasons:
        reasons.append(f"风险分 {risk:.2f}, 未触发单项阈值")

    return SlideshowRisk(
        risk=round(risk, 4),
        verdict=verdict,
        components={k: round(v, 4) for k, v in present.items()},
        measured={k: round(float(raw[k]), 4) for k in present},  # type: ignore[arg-type]
        missing=missing,
        reasons=tuple(reasons),
        weights={k: round(w[k], 4) for k in present},
    )


__all__ = [
    "DEFAULT_THRESHOLDS",
    "DEFAULT_WEIGHTS",
    "SlideshowRisk",
    "score_slideshow_risk",
    "similarity_to_repeat",
]
