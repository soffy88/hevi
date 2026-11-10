"""Hevi Handdraw Line: 4 verified style definitions and parameters.

Provides style configurations and metadata for:
- 1: 极简黑白线条讲解漫画 (xkcd 火柴人)
- 8: 水墨写意 (传统水墨，墨分五色)
- 10: 情绪叙事淡彩速写 (细铅笔线，单处高饱和点缀)
- 17: 墨线绘本 (经典墨线，水彩平涂)

All styles comply with upstream hand-drawn-styles recipes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from hevi.layer4_legacy.handdraw import HANDDRAW_ROOT

STYLES_DIR = HANDDRAW_ROOT / "dependencies" / "hand-drawn-styles"


@dataclass(frozen=True)
class HanddrawStyleConfig:
    style_id: str
    name: str
    chinese_name: str
    paper_color: str
    ink_color: str
    accent_color: str
    marker_color: str
    font_color: str
    line_spec: str
    palette_spec: str
    shading_spec: str
    texture_spec: str
    background_spec: str
    recipe_file: str
    base_recipe: str = ""
    library_id: str = ""
    theme_color_id: str = ""


SUPPORTED_STYLES: dict[str, HanddrawStyleConfig] = {
    "1": HanddrawStyleConfig(
        style_id="1",
        name="minimal_black_white_line",
        chinese_name="极简黑白线条讲解漫画",
        paper_color="#FDFBF7",
        ink_color="#181818",
        accent_color="#282828",
        marker_color="#F2D024",
        font_color="#181818",
        line_spec="极简均匀粗细黑线，清晰单线，无排线无多余杂线",
        palette_spec="纯黑与米白底纸，局部使用淡黄记号笔强调",
        shading_spec="无明暗、无阴影、无渐变平涂",
        texture_spec="平整细腻米白绘图纸质感",
        background_spec="留白米白纸底，无背景杂物",
        recipe_file="recipes/1.md",
    ),
    "8": HanddrawStyleConfig(
        style_id="8",
        name="chinese_ink_wash",
        chinese_name="水墨写意",
        paper_color="#F5EFEB",
        ink_color="#1F2326",
        accent_color="#C23531",  # 朱红印泥
        marker_color="#C23531",
        font_color="#202224",
        line_spec="毛笔水墨笔触，见焦浓重淡清变化与飞白枯笔",
        palette_spec="水墨黑灰为主，以朱红印章与淡赭石点缀",
        shading_spec="宣纸墨晕自然晕开，依靠水分渐变形成写意块面",
        texture_spec="生宣纸纹理，微有吸水渗化纤维感",
        background_spec="传统生宣纸米黄底色，大面积留白",
        recipe_file="recipes/8.md",
    ),
    "10": HanddrawStyleConfig(
        style_id="10",
        name="emotional_light_watercolor",
        chinese_name="情绪叙事淡彩速写",
        paper_color="#FBFBF9",
        ink_color="#2B3E50",  # 靛蓝速写线
        accent_color="#E86328",  # 高饱和橙色点缀
        marker_color="#E86328",
        font_color="#233445",
        line_spec="松散灵动靛蓝速写线，微带情绪手绘抖动",
        palette_spec="大面积留白，全画单处高饱和暖橙关键点缀与淡腮红",
        shading_spec="局部透明淡彩水粉平涂，边缘自然收束",
        texture_spec="冷压水彩纸微颗粒纸纹",
        background_spec="约七成纯净留白，无厚重背景涂色",
        recipe_file="recipes/10.md",
    ),
    "17": HanddrawStyleConfig(
        style_id="17",
        name="inked_storybook",
        chinese_name="墨线绘本",
        paper_color="#FAF3DD",  # 暖色绘本纸
        ink_color="#1E2522",
        accent_color="#D4A373",  # 暖色木调
        marker_color="#CCD5AE",  # 橄榄淡绿
        font_color="#1C211E",
        line_spec="钢笔工整墨线，闭合轮廓清晰，转折圆润柔和",
        palette_spec="暖桃色、低饱和橄榄绿与米黄平涂水彩",
        shading_spec="平涂分块上色，色块内色泽温润均匀",
        texture_spec="厚重精装绘本纸张微粗质感",
        background_spec="暖桃米色温和渐变底板",
        recipe_file="recipes/17.md",
    ),
}


def get_style_config(style_id: str | int, *, theme_color_id: str | None = None) -> HanddrawStyleConfig:
    key = str(style_id).strip()
    if key in SUPPORTED_STYLES:
        return SUPPORTED_STYLES[key]
    # Library style ids (FA-001 … FI-034) map onto one of the four procedural
    # recipes plus the library theme palette.  This keeps the CPU illustrator
    # deterministic while making the full catalogue selectable.
    return _library_style_config(key, theme_color_id=theme_color_id)


def _rgb(hex_code: str) -> tuple[int, int, int]:
    clean = str(hex_code or "").lstrip("#")
    return int(clean[0:2], 16), int(clean[2:4], 16), int(clean[4:6], 16)


def _hex(rgb: tuple[float, float, float]) -> str:
    return "#" + "".join(f"{max(0, min(255, round(c))):02X}" for c in rgb)


def _mix(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))  # type: ignore[return-value]


def _luma(rgb: tuple[int, int, int]) -> float:
    return (0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]) / 255.0


def _library_base_recipe(category: str, traits: str) -> str:
    if any(k in traits for k in ("水墨", "毛笔", "宣纸", "墨晕", "飞白", "墨分五色")):
        return "8"
    if any(k in traits for k in ("水彩", "淡彩", "水粉", "透明叠染", "晕染", "彩铅")):
        return "10"
    if any(k in traits for k in ("黑白", "单线", "钢笔", "墨线", "极简线", "线条")):
        return "1" if category in {"FA", "FH"} else "17"
    if category in {"FA", "FH"}:
        return "1"
    if category == "FD":
        return "10"
    return "17"


def _library_style_config(style_id: str, *, theme_color_id: str | None = None) -> HanddrawStyleConfig:
    from hevi.style_library import catalog

    style = catalog.get_style(style_id)
    color = catalog.get_color(theme_color_id or "C-27")
    accent = _rgb(color.get("hex") or "#C8A96A")
    paper = _mix((250, 246, 238), accent, 0.10)
    ink = _mix((30, 28, 26), accent, 0.10)
    if abs(_luma(accent) - _luma(paper)) < 0.22:
        accent = _mix(accent, (0, 0, 0), 0.30)
    marker = _mix(accent, paper, 0.55)
    category = style.get("category", "FA")
    traits = style.get("traits", "")
    base = _library_base_recipe(category, traits)
    return HanddrawStyleConfig(
        style_id=style["id"],
        name=style.get("generation_name", style["id"]),
        chinese_name=style.get("generation_name", style["id"]),
        paper_color=_hex(paper),
        ink_color=_hex(ink),
        accent_color=_hex(accent),
        marker_color=_hex(marker),
        font_color=_hex(ink),
        line_spec=traits or "手绘线条，清楚外轮廓",
        palette_spec=f"主题色：{color.get('name_zh','')}（{color.get('hex','')}），纸色与点缀色同源",
        shading_spec="平涂/淡彩，按所选风格特征收束",
        texture_spec="纸张颗粒与手绘笔压",
        background_spec="留白纸底，无复杂背景",
        recipe_file=f"library/{style['id']}.md",
        base_recipe=base,
        library_id=style["id"],
        theme_color_id=color["id"],
    )


def list_handdraw_styles() -> list[dict[str, Any]]:
    return [
        {
            "id": cfg.style_id,
            "name": cfg.name,
            "chinese_name": cfg.chinese_name,
            "paper_color": cfg.paper_color,
            "ink_color": cfg.ink_color,
            "accent_color": cfg.accent_color,
            "library_id": cfg.library_id,
        }
        for cfg in SUPPORTED_STYLES.values()
    ]
