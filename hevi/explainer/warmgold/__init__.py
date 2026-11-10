"""暖黑金图解：方法、零件、逐拍脚本与渲染。"""

from __future__ import annotations

from hevi.explainer.warmgold.parts import (
    PART_IDS,
    PARTS,
    PARTS_BY_ID,
    get_part,
    parts_manifest,
    write_parts,
)
from hevi.explainer.warmgold.style import (
    STYLE_CARD,
    STYLE_ID,
    STYLE_NAME,
    style_card,
    write_style_card,
)

__all__ = [
    "STYLE_CARD",
    "STYLE_ID",
    "STYLE_NAME",
    "style_card",
    "write_style_card",
    "PART_IDS",
    "PARTS",
    "PARTS_BY_ID",
    "get_part",
    "parts_manifest",
    "write_parts",
]
