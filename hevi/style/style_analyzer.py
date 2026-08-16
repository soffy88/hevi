"""风格参数分析 —— 参考图 → 确定性风格画像(3O 内化 Round 3e,补 draft_from_reference 的确定性层)。

dramaclaw style_analyzer + hevi 既有 draft_from_reference(VLM 短语草稿)之间缺的:
**确定性视觉画像** —— 不依赖 LLM 就能从参考图提取可量化的风格参数(主色板/亮度/
饱和度/对比度/暖冷),与 VLM 短语草稿合并成完整 StyleProfile。这让 StylePack 从
"参考→草稿"升级为"参考→可量化画像 + 语言草稿"。

确定性部分(可测,纯 PIL):主色提取(量化聚类)、亮度/饱和度/对比度统计、暖冷判定、
色板构建;VLM 部分走注入钩子(复用 draft_from_reference 的短语草稿)。

3O 归属(待上游): `oprim.style_analyzer`(确定性画像)。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class StyleProfile:
    """参考图风格画像:确定性视觉参数 + VLM 语言草稿。"""

    source: str
    palette: list[str] = field(default_factory=list)  # 主色板(hex,降序占比)
    palette_shares: list[float] = field(default_factory=list)
    brightness: float = 0.0  # 0-1 平均亮度
    saturation: float = 0.0  # 0-1 平均饱和度
    contrast: float = 0.0  # 亮度标准差
    warmth: float = 0.0  # -1 冷 … +1 暖
    language: dict[str, str] = field(default_factory=dict)  # VLM 草稿 {style, lighting, ...}

    @property
    def dominant_color(self) -> str:
        return self.palette[0] if self.palette else "#000000"

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "palette": self.palette,
            "palette_shares": self.palette_shares,
            "brightness": round(self.brightness, 3),
            "saturation": round(self.saturation, 3),
            "contrast": round(self.contrast, 3),
            "warmth": round(self.warmth, 3),
            "language": self.language,
        }


def _hex(r: int, g: int, b: int) -> str:
    return f"#{r:02x}{g:02x}{b:02x}"


def analyze_reference_image(path: str | Path) -> StyleProfile:
    """确定性画像(纯 PIL,不依赖 LLM):

    - 主色板:量化到 4bit 每通道 → 按占比排序取 top 5。
    - 亮度/饱和度:平均;对比度:亮度标准差;暖冷:(R-B)/(R+B)。
    """
    from PIL import Image

    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"reference image not found: {p}")
    img = Image.open(p).convert("RGB")

    # 降采样加速统计
    img.thumbnail((64, 64))
    px = list(img.getdata())
    n = max(len(px), 1)

    # 量化主色(4bit/通道)
    buckets: dict[str, int] = {}
    r_sum = g_sum = b_sum = 0
    sat_sum = 0.0
    for r, g, b in px:
        r_sum += r
        g_sum += g
        b_sum += b
        mx, mn = max(r, g, b), min(r, g, b)
        sat_sum += (mx - mn) / 255.0
        key = _hex(r & 0xF0, g & 0xF0, b & 0xF0)
        buckets[key] = buckets.get(key, 0) + 1

    ranked = sorted(buckets.items(), key=lambda kv: kv[1], reverse=True)[:5]
    palette = [k for k, _ in ranked]
    shares = [round(v / n, 3) for _, v in ranked]

    r_avg, g_avg, b_avg = r_sum / n, g_sum / n, b_sum / n
    brightness = (r_avg + g_avg + b_avg) / (3 * 255.0)
    saturation = sat_sum / n
    contrast = _luma_std(px)
    warmth = (r_avg - b_avg) / (r_avg + b_avg + 1e-6)

    return StyleProfile(
        source=str(p),
        palette=palette,
        palette_shares=shares,
        brightness=round(brightness, 3),
        saturation=round(saturation, 3),
        contrast=round(contrast, 3),
        warmth=round(max(-1.0, min(1.0, warmth)), 3),
    )


def _luma_std(px: list[tuple[int, int, int]]) -> float:
    luma = [0.299 * r + 0.587 * g + 0.114 * b for r, g, b in px]
    mean = sum(luma) / len(luma)
    var = sum((v - mean) ** 2 for v in luma) / len(luma)
    return float((var ** 0.5) / 255.0)


#: VLM 草稿注入钩子(可复用 draft_from_reference.draft_style_from_reference)。
VlmDraft = Callable[[Path], dict[str, str]]


def build_full_profile(
    image_path: str | Path,
    *,
    vlm_draft: VlmDraft | None = None,
) -> StyleProfile:
    """确定性画像 + 可选 VLM 语言草稿合并为完整画像。"""
    profile = analyze_reference_image(image_path)
    if vlm_draft is not None:
        try:
            profile.language = vlm_draft(Path(image_path))
        except Exception as e:  # VLM 失败不阻断确定性画像
            logger.warning("style_analyzer: vlm draft failed: %s", e)
            profile.language = {}
    return profile


def save_profile(profile: StyleProfile, path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(profile.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def merge_with_draft(profile: StyleProfile, draft: dict[str, str]) -> StyleProfile:
    """把 VLM 草稿并入画像(不覆盖确定性字段)。"""
    return StyleProfile(
        source=profile.source,
        palette=list(profile.palette),
        palette_shares=list(profile.palette_shares),
        brightness=profile.brightness,
        saturation=profile.saturation,
        contrast=profile.contrast,
        warmth=profile.warmth,
        language=dict(draft),
    )
