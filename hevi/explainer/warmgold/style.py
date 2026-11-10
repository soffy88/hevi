"""暖黑金图解 —— 风格卡与排版契约。

只描述“看起来怎样、哪里不能放字”，不包含任何第三方文案或示例主题。
风格卡同时落盘到 ``assets/style_cards/warm_gold.json``，供前端/卡片库读取。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

STYLE_ID = "warm_gold_diagram"
STYLE_NAME = "暖黑金图解"

# 9:16 竖屏画布。
WIDTH = 1080
HEIGHT = 1920
FPS = 24

# 安全区：顶 150 / 底 380 / 右 140（与 BRIEF §3 一致）。
SAFE = {"top": 150, "bottom": 380, "right": 140, "left": 60}

# 字体只用 OFL：Noto Serif/Sans CJK 均为 SIL OFL 1.1。
FONT_BIG = '"Noto Serif CJK SC", "Noto Serif CJK TC", serif'
FONT_SMALL = '"Noto Sans CJK SC", "Noto Sans CJK TC", "WenQuanYi Zen Hei", sans-serif'

STYLE_CARD: dict[str, Any] = {
    "id": STYLE_ID,
    "name": STYLE_NAME,
    "description": "近黑暖棕底、象牙白字、香槟金细线；暗朱红只用于威胁/负面。",
    "palette": {
        "background": "#120E0B",
        "background_soft": "#1B1510",
        "panel": "#201812",
        "ivory": "#F2E8D5",
        "ivory_dim": "#B9AC96",
        "gold": "#C8A96A",
        "gold_bright": "#E4CB92",
        "danger": "#7A2E2A",
        "past": "#6B5B45",
    },
    "lighting": "低照度暖光；正在发生的元素最亮，发生过的暗一档，无关的最暗。",
    "rules": [
        "正在发生最亮，发生过暗一档，无关最暗；过去元素自动淡出。",
        "香槟金只画线/刻度/连接，不铺大面积色块。",
        "暗朱红只用于威胁、损失、负面结果。",
        "一屏一个重点；大字不超过 6 字/秒，小字不超过 7 字/秒。",
        "数字必须带出处或标「示意」。",
    ],
    "typography": {
        "big_font": FONT_BIG,
        "small_font": FONT_SMALL,
        "big_size_px": 92,
        "small_size_px": 44,
        "big_max_chars_per_sec": 6,
        "small_max_chars_per_sec": 7,
    },
    "safety": {**SAFE, "width": WIDTH, "height": HEIGHT},
    "music": "只用用户上传（声明授权）或 hevi 已有可商用曲库。",
    "fonts_license": "SIL OFL 1.1 (Noto Serif/Sans CJK)",
}

# 大字/小字允许的最大字数（供写脚本时快速校验）。
BIG_MAX_CHARS = 34
SMALL_MAX_CHARS = 56


def style_card() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(json.dumps(STYLE_CARD, ensure_ascii=False))
    return data


def asset_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "assets" / "style_cards"


def write_style_card(dest: Path | None = None) -> Path:
    target = Path(dest) if dest else asset_dir() / "warm_gold.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(STYLE_CARD, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def inside_safe(x: int, y: int, pad: int = 0) -> bool:
    """点是否在安全区内。"""
    return (
        SAFE["left"] + pad <= x <= WIDTH - SAFE["right"] - pad
        and SAFE["top"] + pad <= y <= HEIGHT - SAFE["bottom"] - pad
    )


def safe_box() -> dict[str, int]:
    return {
        "x": SAFE["left"],
        "y": SAFE["top"],
        "w": WIDTH - SAFE["left"] - SAFE["right"],
        "h": HEIGHT - SAFE["top"] - SAFE["bottom"],
    }


def text_fits(text: str, size_px: int, *, max_width: int | None = None) -> bool:
    """粗略字宽估计：CJK 约 1em，ASCII 约 0.55em。"""
    width = 0.0
    for ch in text:
        width += 1.0 if ord(ch) > 0x2E80 else 0.55
    return width * size_px <= (max_width if max_width is not None else safe_box()["w"])


def text_width_px(text: str, size_px: int) -> float:
    return sum(1.0 if ord(ch) > 0x2E80 else 0.55 for ch in text) * size_px
