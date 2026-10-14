"""Constants and visual system configurations for RISO B-roll module."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RisoPalette:
    name: str
    paper: str
    ink_a: str  # Primary deep ink (carries structure and all text)
    ink_b: str  # Fluorescent spot ink (one highlight per frame)
    overprint: str  # Multiplied overlay shade
    label: str


PALETTES: dict[str, RisoPalette] = {
    "ink_blue_neon_pink": RisoPalette(
        name="ink_blue_neon_pink",
        paper="#F4EEE1",
        ink_a="#0F1E36",
        ink_b="#FF2A85",
        overprint="#0A1224",
        label="墨蓝×荧光粉",
    ),
    "teal_orange": RisoPalette(
        name="teal_orange",
        paper="#F3EFE6",
        ink_a="#0E3B43",
        ink_b="#FF5D15",
        overprint="#08252C",
        label="深青×橙",
    ),
    "navy_vermilion": RisoPalette(
        name="navy_vermilion",
        paper="#F6F2E7",
        ink_a="#1A2639",
        ink_b="#EB3826",
        overprint="#101824",
        label="藏青×朱红",
    ),
    "ink_black_bright_yellow": RisoPalette(
        name="ink_black_bright_yellow",
        paper="#F4EFE6",
        ink_a="#18181A",
        ink_b="#FFE600",
        overprint="#0F0F10",
        label="墨黑×亮黄",
    ),
}

# Aliases for convenience
PALETTE_ALIASES: dict[str, str] = {
    "blue_pink": "ink_blue_neon_pink",
    "teal_orange": "teal_orange",
    "navy_red": "navy_vermilion",
    "black_yellow": "ink_black_bright_yellow",
}

# 9:16 Canvas geometry
CANVAS_WIDTH = 1080
CANVAS_HEIGHT = 1920
FPS = 30
MISREGISTRATION_PX = 3  # Misalignment of Ink B relative to Ink A

# Safe Zones (1080x1920)
TOP_SAFE_Y = 168        # 0-168: completely empty
BOTTOM_TEXT_Y = 1330    # 168-1330: all text must stay within this range
BOTTOM_SAFE_Y = 1920    # 1330-1920: decorative only (halftone dot floor, registration marks)
RIGHT_CLEAR_X = 940     # 940-1080: button bar safe area, no text allowed
LEFT_MARGIN_X = 80      # 0-80: left margin safe zone

# Animation timing rules
MAX_SETTLE_TIME_S = 2.5  # Main information in place within 2.5 seconds
DEFAULT_DURATION_S = 3.5

# 10 Information template names
TEMPLATE_NAMES = (
    "versus",    # 误区翻转
    "title",     # 章节卡
    "number",    # 数字冲击
    "compare",   # 前后对比
    "converge",  # 收敛归类
    "network",   # 连接密度
    "focus",     # 多选一
    "steps",     # 流程步骤
    "shot",      # 截图锚点
    "quote",     # 金句
)

# Text slot limits and font size minimums
SLOT_CONSTRAINTS: dict[str, dict[str, Any]] = {
    "title": {"max_chars": 16, "min_font_px": 52},
    "subtitle": {"max_chars": 24, "min_font_px": 32},
    "tag": {"max_chars": 10, "min_font_px": 24},
    "number_val": {"max_chars": 12, "min_font_px": 80},
    "number_unit": {"max_chars": 8, "min_font_px": 36},
    "body": {"max_chars": 28, "min_font_px": 32},
    "quote": {"max_chars": 36, "min_font_px": 44},
    "item": {"max_chars": 18, "min_font_px": 28},
    "caption": {"max_chars": 20, "min_font_px": 24},
}
