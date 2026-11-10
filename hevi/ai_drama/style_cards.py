"""Style cards for ai_drama / series.

A style card is a reusable look for a whole series: a cover image, one English
style prompt that is appended to every image prompt, a negative prompt, a small
palette, and a flat-light makeup reference (平光定妆参考).  The eight built-in
cards are self-made with the local SD-Turbo engine (``scripts/gen_style_cards.py``);
no image is copied from another site.

The card is deliberately data-only.  Selecting one sets fields on the series and
on the episode script; the image pipeline already concatenates those fields into
its render prompts, so a card cannot silently change the renderer.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

_ASSET_DIR = Path(__file__).resolve().parents[2] / "assets" / "style_cards"

STYLE_CARDS: tuple[dict[str, Any], ...] = (
    {
        "id": "anime_cel",
        "name": "日系赛璐璐动画",
        "description": "干净线稿 + 平涂色块 + 柔和边缘光，适合日常/恋爱短剧。",
        "style_prompt": (
            "Japanese cel-shaded anime illustration, clean bold line art, flat pastel colors, "
            "soft rim light, simple background, consistent character design"
        ),
        "style_prompt_zh": "日系赛璐璐动画，干净线稿，平涂色块，柔和边缘光，简洁背景。",
        "negative_prompt": "photorealistic, 3d render, heavy texture, extra limbs, text, watermark",
        "palette": ["#F7D9C4", "#8FB3D9", "#2E2A33", "#F4EFE6"],
        "lighting": "flat even light, no hard shadow",
        "cover": "anime_cel_cover.jpg",
        "makeup": "anime_cel_makeup.jpg",
    },
    {
        "id": "guofeng_ink",
        "name": "国风水墨",
        "description": "水墨晕染 + 宣纸底色 + 留白，适合古风/历史题材。",
        "style_prompt": (
            "traditional Chinese ink wash painting, flowing brush strokes, muted rice-paper tone, "
            "elegant hanfu figure, generous negative space, soft diffusion"
        ),
        "style_prompt_zh": "国风水墨，流动笔触，宣纸底色，古装人物，大面积留白。",
        "negative_prompt": "anime, neon, plastic, hard shadow, text, watermark",
        "palette": ["#E8E1D3", "#3A3A3A", "#8C6A4A", "#B54B3C"],
        "lighting": "soft diffused light, no directional shadow",
        "cover": "guofeng_ink_cover.jpg",
        "makeup": "guofeng_ink_makeup.jpg",
    },
    {
        "id": "american_comic",
        "name": "美式漫画",
        "description": "粗墨线 + 网点 + 高饱和主色，适合热血/悬疑。",
        "style_prompt": (
            "american comic book illustration, bold black ink outlines, halftone dots, "
            "dramatic shading, vibrant primary colors, dynamic composition"
        ),
        "style_prompt_zh": "美式漫画，粗黑墨线，网点阴影，高饱和主色，强构图。",
        "negative_prompt": "soft pastel, watercolor, low contrast, text, watermark",
        "palette": ["#E23B2E", "#1F4E8C", "#F2C14E", "#F5F1E8"],
        "lighting": "hard directional comic light",
        "cover": "american_comic_cover.jpg",
        "makeup": "american_comic_makeup.jpg",
    },
    {
        "id": "soft3d",
        "name": "柔和 3D 动画",
        "description": "圆润造型 + 柔和棚拍光 + 低饱和，适合亲子/治愈。",
        "style_prompt": (
            "soft 3d animated character, rounded friendly shapes, subsurface scattering, "
            "pastel palette, studio softbox lighting, plain seamless background"
        ),
        "style_prompt_zh": "柔和 3D 动画，圆润造型，柔和棚拍光，低饱和配色。",
        "negative_prompt": "harsh shadow, photorealistic skin, anime line art, text, watermark",
        "palette": ["#F6E7D8", "#A8D8C9", "#6C7BA3", "#FFFFFF"],
        "lighting": "studio softbox, flat even light",
        "cover": "soft3d_cover.jpg",
        "makeup": "soft3d_makeup.jpg",
    },
    {
        "id": "retro_film",
        "name": "复古胶片写实",
        "description": "35mm 颗粒 + 暖钨丝光 + 青橙色调，适合都市/情感。",
        "style_prompt": (
            "cinematic 35mm film photograph, visible grain, warm tungsten light, "
            "shallow depth of field, muted teal and orange grade, natural skin"
        ),
        "style_prompt_zh": "复古胶片写实，35mm 颗粒，暖钨丝光，浅景深，青橙色调。",
        "negative_prompt": "cartoon, anime, oversaturated, plastic skin, text, watermark",
        "palette": ["#D9A066", "#2F4858", "#E8E1D5", "#7A5C43"],
        "lighting": "warm practical light, soft falloff",
        "cover": "retro_film_cover.jpg",
        "makeup": "retro_film_makeup.jpg",
    },
    {
        "id": "cyber_neon",
        "name": "赛博霓虹",
        "description": "洋红/青色轮廓光 + 湿地面反光，适合科幻/悬疑。",
        "style_prompt": (
            "cyberpunk portrait, magenta and cyan rim lights, wet reflective ground, "
            "dark background, glowing accents, cinematic haze"
        ),
        "style_prompt_zh": "赛博霓虹，洋红与青色轮廓光，湿地面反光，深色背景。",
        "negative_prompt": "daylight, pastel, flat illustration, text, watermark",
        "palette": ["#FF3FA4", "#25D8E8", "#141826", "#6C3CF0"],
        "lighting": "neon rim light, low-key",
        "cover": "cyber_neon_cover.jpg",
        "makeup": "cyber_neon_makeup.jpg",
    },
    {
        "id": "clay_stopmotion",
        "name": "黏土定格",
        "description": "橡皮泥质感 + 指纹痕迹 + 柔和棚光，适合轻喜剧/儿童。",
        "style_prompt": (
            "claymation stop-motion character, plasticine texture, handmade fingerprints, "
            "soft studio light, plain colored backdrop, miniature set"
        ),
        "style_prompt_zh": "黏土定格，橡皮泥质感，手工指纹，柔和棚光，纯色背景。",
        "negative_prompt": "photorealistic, anime, smooth plastic, text, watermark",
        "palette": ["#F2C7A5", "#7FB3A8", "#C96A5A", "#F7F1E6"],
        "lighting": "soft studio light, gentle shadow",
        "cover": "clay_stopmotion_cover.jpg",
        "makeup": "clay_stopmotion_makeup.jpg",
    },
    {
        "id": "flat_vector",
        "name": "极简扁平插画",
        "description": "几何色块 + 无渐变 + 有限配色，适合知识/职场。",
        "style_prompt": (
            "flat vector illustration, minimal geometric shapes, limited pastel palette, "
            "no gradients, clean composition, subtle grain"
        ),
        "style_prompt_zh": "极简扁平插画，几何色块，有限配色，无渐变，干净构图。",
        "negative_prompt": "photorealistic, 3d, detailed texture, text, watermark",
        "palette": ["#F3E9DC", "#5B8C85", "#E8A87C", "#334E68"],
        "lighting": "flat light, no shadow",
        "cover": "flat_vector_cover.jpg",
        "makeup": "flat_vector_makeup.jpg",
    },
)

_BY_ID = {card["id"]: card for card in STYLE_CARDS}


def _resolve(path: str) -> str:
    candidate = _ASSET_DIR / path
    return str(candidate) if candidate.is_file() else ""


def list_style_cards() -> list[dict[str, Any]]:
    """Every built-in card with resolved cover / makeup paths ('' when absent)."""
    cards = []
    for card in STYLE_CARDS:
        item = dict(card)
        item["cover_path"] = _resolve(str(card["cover"]))
        item["makeup_path"] = _resolve(str(card["makeup"]))
        item["available"] = bool(item["cover_path"])
        cards.append(item)
    return cards


def get_style_card(card_id: str) -> dict[str, Any] | None:
    card = _BY_ID.get(str(card_id or "").strip())
    if card is None:
        return None
    item = dict(card)
    item["cover_path"] = _resolve(str(card["cover"]))
    item["makeup_path"] = _resolve(str(card["makeup"]))
    item["available"] = bool(item["cover_path"])
    return item


def apply_style_card(series: dict[str, Any], card_id: str) -> dict[str, Any]:
    """Attach one card to a series.  Unknown ids raise; nothing is invented."""
    card = get_any_style_card(card_id)
    if card is None:
        raise KeyError(f"unknown style card: {card_id!r}")
    series["style_card"] = card["id"]
    series["style_card_name"] = card["name"]
    series["style"] = card["id"]
    series["style_prompt"] = card["style_prompt"]
    series["style_prompt_zh"] = card["style_prompt_zh"]
    series["style_negative"] = card["negative_prompt"]
    series["style_palette"] = list(card["palette"])
    series["style_lighting"] = card["lighting"]
    series["style_cover"] = card["cover_path"]
    series["style_makeup_reference"] = card["makeup_path"]
    return series


def style_prompt_for(series: dict[str, Any]) -> str:
    """The reusable prompt appended to character/scene image prompts."""
    return str(series.get("style_prompt") or "").strip()


def style_card_findings(series: dict[str, Any]) -> list[dict[str, Any]]:
    """A selected card must exist and its reference images must be present."""
    card_id = str(series.get("style_card") or "").strip()
    if not card_id:
        return []
    card = get_style_card(card_id)
    findings: list[dict[str, Any]] = []
    if card is None:
        findings.append({"rule": "C-STYLE", "severity": "major",
                         "message": f"风格卡 {card_id} 不存在", "ref": card_id})
        return findings
    if not card["cover_path"]:
        findings.append({"rule": "C-STYLE", "severity": "minor",
                         "message": f"风格卡 {card_id} 缺少封面图", "ref": card_id})
    if not card["makeup_path"]:
        findings.append({"rule": "C-STYLE", "severity": "minor",
                         "message": f"风格卡 {card_id} 缺少平光定妆参考", "ref": card_id})
    return findings


__all__ = [
    "STYLE_CARDS",
    "apply_style_card",
    "get_style_card",
    "list_style_cards",
    "style_card_findings",
    "style_prompt_for",
]


# ---------------------------------------------------------------------------
# Library merge (S27)
# ---------------------------------------------------------------------------


def library_style_cards() -> list[dict[str, Any]]:
    """The handraw-style catalogue as ai_drama cards.

    The 8 built-in self-made cards stay the default (they have local cover and
    makeup references).  Library cards are additive: id ``hw_<STYLE-ID>``,
    no copied preview image, and a prompt built from the library style name and
    category.  Duplicates by normalised generation name are dropped.
    """
    from hevi.style_library.integrations import ai_drama_library_cards

    builtin_names = {str(card.get("name") or "").strip().lower() for card in STYLE_CARDS}
    out: list[dict[str, Any]] = []
    for card in ai_drama_library_cards():
        name = str(card.get("name") or "").strip().lower()
        if name and name in builtin_names:
            continue
        out.append(card)
    return out


def list_all_style_cards(*, include_library: bool = True) -> list[dict[str, Any]]:
    cards = list_style_cards()
    if include_library:
        cards.extend(library_style_cards())
    return cards


def get_any_style_card(card_id: str) -> dict[str, Any] | None:
    card = get_style_card(card_id)
    if card is not None:
        return card
    text = str(card_id or "").strip()
    if text.startswith("hw_"):
        for card in library_style_cards():
            if card["id"] == text:
                return card
    return None
