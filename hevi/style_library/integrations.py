"""Bridges from the style library into hevi's product lines.

Every bridge keeps the upstream index read-only and returns plain data, so a
caller can pin the ids in its own manifest.  Nothing here re-renders a whole
film: the canvas helper only marks the affected nodes dirty.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from hevi.style_library import ATTRIBUTION, catalog

# English prompt tokens per category (the upstream traits are Chinese; SD's
# CLIP text encoder needs English).  The generation name adds the specific look.
_CATEGORY_TOKENS = {
    "FA": "editorial cartoon illustration, loose hand-drawn ink line, flat spot color, expressive deadpan character, generous white space",
    "FB": "classic storybook illustration, soft ink and watercolor wash, visible paper grain, gentle narrative mood",
    "FC": "modern graphic illustration, bold geometric shapes, limited flat palette, clean composition, subtle grain",
    "FD": "contemporary Japanese-style illustration, delicate linework, muted pastel palette, quiet emotional atmosphere",
    "FE": "Chinese heritage illustration, brush-and-ink or gongbi linework, rice-paper texture, restrained traditional palette",
    "FF": "handmade 3D / clay / paper-craft illustration, tactile material, soft studio light, miniature set",
    "FG": "anime cel-shaded illustration, clean line art, flat color, expressive character design",
    "FH": "experimental mixed-media illustration, collage and print textures, bold graphic contrast",
    "FI": "cinematic photography, natural light, realistic texture, controlled depth of field",
}

_NEGATIVE = (
    "photorealistic unless requested, extra limbs, deformed anatomy, blurry, low quality, "
    "text, watermark, signature, logo, oversaturated"
)

_COMPOSITION_TOKENS = {
    "social-card": "social media card layout, clear reading order, generous negative space",
    "social-cards": "social media card layout, clear reading order, generous negative space",
    "infographic": "infographic layout, clear hierarchy, labels and connecting lines",
    "infographics": "infographic layout, clear hierarchy, labels and connecting lines",
    "comic-storyboard": "comic panel layout, clear panel borders, readable action staging",
    "ip-character": "character sheet layout, front and side views, consistent proportions",
    "ip-characters": "character sheet layout, front and side views, consistent proportions",
    "ecommerce": "product hero layout, clean background, commercial lighting",
}


def comic_style(style_id: str, theme_color_id: str = "C-27") -> Any:
    """A StylePreset-compatible object for comic narration / keyframes."""
    from hevi.layer4_legacy.keyframe.oprim_impl.style_presets import DEFAULT_STYLE, get_style_preset

    style = catalog.get_style(style_id)
    color = catalog.get_color(theme_color_id)
    palette = catalog.theme_palette(color["id"])
    base = get_style_preset(DEFAULT_STYLE)
    tokens = (
        f"{style.get('generation_name','')}, "
        f"{_CATEGORY_TOKENS.get(style.get('category',''), 'hand-drawn illustration')}, "
        f"dominant theme color {color.get('name_en','')} ({color.get('hex','')}), "
        "consistent character design across panels, 8k masterpiece"
    )
    return replace(
        base,
        name=f"hw_{style['id']}",
        style_tokens=tokens,
        negative_prompt=_NEGATIVE,
        subtitle_primary=_ass_color(palette["ivory"]),
        subtitle_outline="&H00000000",
        subtitle_back="&H80000000",
        bubble_primary=_ass_color(palette["background"]),
        bubble_outline=_ass_color(palette["accent"]),
    )


def _ass_color(hex_code: str) -> str:
    rgb = hex_code.lstrip("#")
    if len(rgb) != 6:
        return "&H00FFFFFF"
    return f"&H00{rgb[4:6]}{rgb[2:4]}{rgb[0:2]}".upper()


def layout_for_stage(stage: str) -> dict[str, Any]:
    """Pick a layout family for a production stage (manifest-friendly)."""
    stage = str(stage or "").lower()
    if stage in {"social", "xiaohongshu", "card", "cover"}:
        return catalog.get_layout("SC-001")
    if stage in {"storyboard", "comic", "drama", "keyframe"}:
        return catalog.get_layout("SB-001")
    if stage in {"character", "ip", "cast"}:
        return catalog.get_layout("IP-001")
    if stage in {"ecommerce", "product"}:
        return catalog.get_layout("EC-001")
    return catalog.get_layout("IG-003")


def layout_plan(
    stage: str,
    *,
    style_id: str = "FA-001",
    theme_color_id: str = "C-27",
    subject: str = "",
) -> dict[str, Any]:
    layout = layout_for_stage(stage)
    style = catalog.get_style(style_id)
    color = catalog.get_color(theme_color_id)
    return {
        "stage": stage,
        "layout": layout,
        "style": catalog.style_brief(style),
        "theme_color": color,
        "prompt_zh": (
            f"图型：{layout['name']}。风格名称：{style.get('generation_name','')}。"
            f"主题色：{color.get('name_zh','')}。主题：{subject or '按脚本内容'}。"
        ),
        "prompt_en": (
            f"Layout: {layout.get('name_en') or layout['name']}. "
            f"Style: {style.get('generation_name','')}. Theme color: {color.get('name_en','')}. "
            f"Subject: {subject or 'the script content'}. "
            f"{_COMPOSITION_TOKENS.get(layout.get('category',''), '')}"
        ),
        "locked": {"style_id": style["id"], "theme_color_id": color["id"]},
        "attribution": ATTRIBUTION,
    }


def ai_drama_library_cards() -> list[dict[str, Any]]:
    """Library styles as ai_drama cards (no duplication with the 8 built-ins)."""
    cards: list[dict[str, Any]] = []
    for style in catalog.load_index()["styles"]:
        palette = catalog.theme_palette("C-27")
        cards.append({
            "id": f"hw_{style['id']}",
            "name": style.get("generation_name") or style["id"],
            "description": style.get("traits", "")[:120],
            "source": "handraw",
            "handraw_style_id": style["id"],
            "style_prompt": (
                f"{style.get('generation_name','')}, "
                f"{_CATEGORY_TOKENS.get(style.get('category',''), 'hand-drawn illustration')}, "
                "consistent character design"
            ),
            "style_prompt_zh": style.get("traits", ""),
            "negative_prompt": _NEGATIVE,
            "palette": [palette["background"], palette["ivory"], palette["accent"], palette["panel"]],
            "lighting": "flat even light, no hard shadow",
            "cover": "",
            "makeup": "",
            "cover_path": "",
            "makeup_path": "",
            "available": False,
            "credit_removed": bool(style.get("credit_removed")),
            "attribution": ATTRIBUTION,
        })
    return cards


def apply_style_to_nodes(
    nodes: list[dict[str, Any]],
    *,
    style_id: str,
    theme_color_id: str = "C-27",
    node_keys: list[str] | None = None,
) -> dict[str, Any]:
    """Set the locked style on visual nodes; return the nodes to re-run.

    Only visual/generative node types are touched.  Text-only nodes keep their
    config, so a style change does not invalidate an approved script.
    """
    style = catalog.get_style(style_id)
    color = catalog.get_color(theme_color_id)
    locked = {"style_id": style["id"], "theme_color_id": color["id"]}
    visual_types = {
        "video", "image", "keyframe", "illustration", "cover", "storyboard",
        "comic", "handdraw", "segment", "render", "broll",
    }
    keys = set(node_keys or [])
    affected: list[str] = []
    updated: list[dict[str, Any]] = []
    for node in nodes:
        item = dict(node)
        key = str(item.get("node_id") or item.get("id") or "")
        node_type = str(item.get("node_type") or item.get("type") or "")
        config = dict(item.get("config") or {})
        is_visual = node_type in visual_types or any(
            k in config for k in ("style_id", "handraw_style_id", "theme_color_id")
        )
        if is_visual and (not keys or key in keys):
            config["style_id"] = style["id"]
            config["handraw_style_id"] = style["id"]
            config["theme_color_id"] = color["id"]
            config["style_lock"] = locked
            item["config"] = config
            affected.append(key)
        updated.append(item)
    return {
        "nodes": updated,
        "affected": affected,
        "locked": locked,
        "reason": f"{style['id']} / {color['id']} 变化，仅重做 {len(affected)} 个受影响节点及其下游。",
        "attribution": ATTRIBUTION,
    }


def warmgold_script(script: dict[str, Any], *, theme_color_id: str, layout_id: str = "IG-003") -> dict[str, Any]:
    """Attach a library theme palette + layout to a warm-gold explainer script."""
    color = catalog.get_color(theme_color_id)
    layout = catalog.get_layout(layout_id)
    out = dict(script)
    out["theme_color_id"] = color["id"]
    out["theme_color"] = color
    out["layout_id"] = layout["id"]
    out["layout"] = layout
    out["palette"] = catalog.theme_palette(color["id"])
    out["style_lock"] = {"theme_color_id": color["id"], "layout_id": layout["id"]}
    return out


def style_summary(style_id: str, theme_color_id: str = "C-27") -> dict[str, Any]:
    style = catalog.get_style(style_id)
    color = catalog.get_color(theme_color_id)
    return {
        "style": catalog.style_brief(style),
        "theme_color": color,
        "palette": catalog.theme_palette(color["id"]),
        "use_cases": style.get("use_cases", []),
        "attribution": ATTRIBUTION,
    }


__all__ = [
    "ai_drama_library_cards",
    "apply_style_to_nodes",
    "comic_style",
    "layout_for_stage",
    "layout_plan",
    "style_summary",
    "warmgold_script",
]
