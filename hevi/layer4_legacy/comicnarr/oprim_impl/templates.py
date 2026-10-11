"""Style templates for comic narration line.

3O Pillar: oprim.comicnarr_templates
"""

from __future__ import annotations

from hevi.layer4_legacy.comicnarr.oprim_impl.contracts import ComicStyle

COMIC_STYLES: dict[str, ComicStyle] = {
    "comic_color": ComicStyle(
        name="comic_color",
        style_tokens=(
            "comic book art, colorful graphic novel illustration, vibrant flat colors, "
            "bold clean lineart, dynamic composition, expressive comic panel aesthetic, 8k masterpiece"
        ),
        negative_prompt=(
            "photorealistic, photo, 3d render, washed out, low quality, blurry, deformed anatomy, "
            "extra limbs, monochrome, grayscale, text, watermark"
        ),
        subtitle_style="comic_yellow_banner",
        transition="slideleft",
        bgm_mood="bright",
    ),
    "manga_bw": ComicStyle(
        name="manga_bw",
        style_tokens=(
            "black and white manga style, Japanese comic panel, monochrome ink line art, "
            "clean screentone, dynamic hatching, expressive graphic novel illustration, masterpiece"
        ),
        negative_prompt=(
            "color, colorful, painting, photo, realistic, 3d, gradient, blurry, low quality, "
            "watermark, text"
        ),
        subtitle_style="manga_high_contrast",
        transition="fade",
        bgm_mood="warm",
    ),
}


def get_style_template(style_name: str = "comic_color") -> ComicStyle:
    """Retrieve style template by name or fallback to comic_color."""
    clean = (style_name or "").strip().lower()
    if clean in COMIC_STYLES:
        return COMIC_STYLES[clean]
    for key, val in COMIC_STYLES.items():
        if key in clean or clean in key:
            return val
    return COMIC_STYLES["comic_color"]


__all__ = [
    "COMIC_STYLES",
    "get_style_template",
]
