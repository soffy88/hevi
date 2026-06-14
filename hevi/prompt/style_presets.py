"""hevi business style presets — topic/style descriptions for inject_visual_style."""

__all__ = ["STYLE_PRESETS", "get_style_preset"]

# Keys match inject_visual_style kwargs: style, lighting, camera, color_grade.
STYLE_PRESETS: dict[str, dict[str, str | None]] = {
    "科普": {
        "style": "educational clear",
        "lighting": "bright even",
        "camera": "smooth pan",
        "color_grade": None,
    },
    "严肃": {
        "style": "serious documentary",
        "lighting": "dramatic",
        "camera": "slow push",
        "color_grade": None,
    },
    "搞笑": {
        "style": "playful vibrant",
        "lighting": "warm",
        "camera": "dynamic",
        "color_grade": None,
    },
}


def get_style_preset(name: str) -> dict[str, str | None]:
    """Return style preset dict for inject_visual_style kwargs.

    Raises:
        ValueError: If the preset name is unknown.
    """
    if name not in STYLE_PRESETS:
        raise ValueError(f"Unknown style preset: {name!r}. Valid: {list(STYLE_PRESETS)}")
    return STYLE_PRESETS[name]
