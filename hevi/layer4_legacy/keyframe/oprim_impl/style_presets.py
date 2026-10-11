"""Shared keyframe style presets (DRAMAKEY / COMICNARR).

Single source of truth for the illustration styles used by the keyframe layer.
Both the ``dramakey`` drama pipeline and the ``comicnarr`` comic-narration line
import from here so the default look stays consistent and non-photoreal.

Exports:
    StylePreset   -- frozen dataclass describing one style
    STYLE_PRESETS -- mapping name -> StylePreset
    DEFAULT_STYLE -- name of the default comic-narration style
    get_style_preset(name)  -> StylePreset (with fuzzy fallback)
    list_style_presets()    -> sorted names

Fields (minimum required by the COMICNARR shared-preset contract):
    style_tokens, negative_prompt, subtitle_style, bgm_mood, transition,
    postprocess

3O Pillar: oprim.keyframe_style_presets
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

#: Default style for the ``comic_narration`` product line (non-photoreal guofeng anime).
DEFAULT_STYLE = "guofeng_anime"


@dataclass(frozen=True)
class StylePreset:
    """A reusable illustration style for keyframe generation.

    ``postprocess`` names an optional deterministic post-pass applied to the
    generated keyframe (e.g. ``manga_bw`` = grayscale + halftone screentone).
    Subtitle fields are rendering hints consumed by subtitle stylers; they are
    inert for non-video consumers.
    """

    name: str
    style_tokens: str
    negative_prompt: str
    subtitle_style: str
    transition: str
    bgm_mood: str = "bright"
    postprocess: str = "none"

    # Subtitle rendering hints (bottom banner / default mode)
    font_size: int = 56
    font_name: str = "WenQuanYi Zen Hei"
    subtitle_primary: str = "&H00FFFFFF"
    subtitle_outline: str = "&H00000000"
    subtitle_back: str = "&H80000000"
    subtitle_border_style: int = 1
    subtitle_outline_width: int = 5
    subtitle_margin_v: int = 220

    # Subtitle rendering hints (bubble / speech-box mode)
    bubble_font_size: int = 54
    bubble_primary: str = "&H00000000"
    bubble_outline: str = "&H0080EAFF"
    bubble_back: str = "&H00000000"

    #: Product lines that should default to this style (informational).
    default_for: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return asdict(self)


STYLE_PRESETS: dict[str, StylePreset] = {
    "comic_color": StylePreset(
        name="comic_color",
        style_tokens=(
            "comic book art, colorful graphic novel illustration, vibrant flat colors, "
            "bold clean lineart, dynamic composition, expressive comic panel aesthetic, "
            "8k masterpiece"
        ),
        negative_prompt=(
            "photorealistic, photo, 3d render, washed out, low quality, blurry, "
            "deformed anatomy, extra limbs, monochrome, grayscale, text, watermark"
        ),
        subtitle_style="bottom_bold",
        transition="slideleft",
        bgm_mood="bright",
        postprocess="none",
        font_size=56,
        subtitle_primary="&H00FFFFFF",
        subtitle_outline="&H00000000",
        subtitle_border_style=1,
        subtitle_outline_width=5,
        subtitle_margin_v=220,
        bubble_font_size=54,
        bubble_primary="&H00101010",
        bubble_outline="&H0000E5FF",  # amber box (BGR)
        bubble_back="&H00000000",
    ),
    "manga_bw": StylePreset(
        name="manga_bw",
        style_tokens=(
            "black and white manga style, Japanese comic panel, monochrome ink line art, "
            "clean screentone, dynamic hatching, expressive graphic novel illustration, "
            "masterpiece"
        ),
        negative_prompt=(
            "color, colorful, painting, photo, realistic, 3d, gradient, blurry, "
            "low quality, watermark, text"
        ),
        subtitle_style="bubble_high_contrast",
        transition="fade",
        bgm_mood="warm",
        postprocess="manga_bw",
        font_size=56,
        subtitle_primary="&H00FFFFFF",
        subtitle_outline="&H00000000",
        subtitle_border_style=1,
        subtitle_outline_width=5,
        subtitle_margin_v=220,
        bubble_font_size=54,
        bubble_primary="&H00FFFFFF",  # white text
        bubble_outline="&H00000000",  # on black box
        bubble_back="&H00000000",
    ),
    "guofeng_anime": StylePreset(
        name="guofeng_anime",
        style_tokens=(
            "Chinese guofeng anime illustration, donghua style, cel-shaded flat colors, "
            "elegant ink-wash accents, delicate clean lineart, atmospheric traditional "
            "Chinese aesthetic, cinematic composition, masterpiece"
        ),
        negative_prompt=(
            "photorealistic, photo, 3d render, realistic, western cartoon, low quality, "
            "blurry, deformed anatomy, extra limbs, oversaturated, text, watermark"
        ),
        subtitle_style="bottom_bold",
        transition="slideleft",
        bgm_mood="warm",
        postprocess="none",
        font_size=56,
        subtitle_primary="&H00FFFFFF",
        subtitle_outline="&H00000000",
        subtitle_border_style=1,
        subtitle_outline_width=5,
        subtitle_margin_v=220,
        bubble_font_size=54,
        bubble_primary="&H00101010",
        bubble_outline="&H0000E5FF",
        bubble_back="&H00000000",
        default_for=("comic_narration",),
    ),
}


def list_style_presets() -> list[str]:
    """Return sorted preset names."""
    return sorted(STYLE_PRESETS)


def get_style_preset(name: str | None = None) -> StylePreset:
    """Resolve a style preset by name with a tolerant fuzzy fallback.

    Falls back to :data:`DEFAULT_STYLE` when *name* is empty or unknown.
    """
    clean = (name or "").strip().lower()
    if not clean:
        return STYLE_PRESETS[DEFAULT_STYLE]
    if clean in STYLE_PRESETS:
        return STYLE_PRESETS[clean]
    for key, val in STYLE_PRESETS.items():
        if key in clean or clean in key:
            return val
    return STYLE_PRESETS[DEFAULT_STYLE]


__all__ = [
    "DEFAULT_STYLE",
    "STYLE_PRESETS",
    "StylePreset",
    "get_style_preset",
    "list_style_presets",
]
