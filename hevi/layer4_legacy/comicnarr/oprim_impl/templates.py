"""Style templates for comic narration line.

Thin adapter over the shared keyframe-layer style presets so that ``dramakey``
and ``comicnarr`` use exactly the same definitions.  The historical names
``COMIC_STYLES`` / ``get_style_template`` are kept for backward compatibility.

3O Pillar: oprim.comicnarr_templates
"""

from __future__ import annotations

from hevi.layer4_legacy.comicnarr.oprim_impl.contracts import ComicStyle
from hevi.layer4_legacy.keyframe.oprim_impl.style_presets import (
    DEFAULT_STYLE,
    STYLE_PRESETS,
    get_style_preset,
    list_style_presets,
)

#: Comic-narration facing view of the shared presets (same objects).
COMIC_STYLES: dict[str, ComicStyle] = dict(STYLE_PRESETS)


def get_style_template(style_name: str = DEFAULT_STYLE) -> ComicStyle:
    """Retrieve style template by name or fallback to the shared default."""
    return get_style_preset(style_name)


__all__ = [
    "COMIC_STYLES",
    "DEFAULT_STYLE",
    "STYLE_PRESETS",
    "get_style_template",
    "list_style_presets",
]
