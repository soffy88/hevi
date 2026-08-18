"""镜头变化幅度分类:决定要不要生末帧、走单图还是双图 I2V。

3O 归属(待上游): `oprim.shot_variation`。
"""

from __future__ import annotations

from hevi.script2video.schemas import VariationType

_LARGE_MARKERS = (
    "航拍",
    "穿越",
    "从全景",
    "推到特写",
    "拉到全景",
    "drone",
    "aerial",
    "extreme long",
    "wide to close",
    "dolly from",
)
_MEDIUM_MARKERS = (
    "新角色",
    "走进画面",
    "转身面对",
    "转过身",
    "面向镜头",
    "appears",
    "enters frame",
    "turns to face",
    "turns around",
)


def classify_variation(
    visual_desc: str,
    *,
    ff_desc: str = "",
    lf_desc: str = "",
    action_beats: list[str] | None = None,
) -> tuple[VariationType, str]:
    """启发式分类。有末帧文本且与首帧差很大时抬到 medium/large。"""
    blob = " ".join(
        part
        for part in (visual_desc, ff_desc, lf_desc, " ".join(action_beats or []))
        if part
    ).lower()
    for marker in _LARGE_MARKERS:
        if marker.lower() in blob:
            return "large", f"matched large marker: {marker}"
    for marker in _MEDIUM_MARKERS:
        if marker.lower() in blob:
            return "medium", f"matched medium marker: {marker}"
    if (
        lf_desc
        and ff_desc
        and lf_desc.strip() != ff_desc.strip()
        and len(lf_desc) > 40
        and _token_delta(ff_desc, lf_desc) >= 0.45
    ):
        return "medium", "first/last frame descriptions diverge"
    return "small", "expression/pose/moderate camera move"


def needs_last_frame(variation_type: VariationType) -> bool:
    return variation_type in ("medium", "large")


def _token_delta(left: str, right: str) -> float:
    left_tokens = set(left.replace("，", " ").replace(",", " ").split())
    right_tokens = set(right.replace("，", " ").replace(",", " ").split())
    if not left_tokens and not right_tokens:
        return 0.0
    union = left_tokens | right_tokens
    inter = left_tokens & right_tokens
    return 1.0 - (len(inter) / len(union))
