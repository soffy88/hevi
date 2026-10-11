"""Comic narration primitives."""

from hevi.layer4_legacy.comicnarr.oprim_impl.contracts import (
    ComicScene,
    ComicScript,
    ComicStyle,
)
from hevi.layer4_legacy.comicnarr.oprim_impl.ken_burns import (
    CAMERA_MOVES,
    build_ken_burns_filter,
)
from hevi.layer4_legacy.comicnarr.oprim_impl.postprocess import (
    apply_style_postprocess,
    is_grayscale,
)
from hevi.layer4_legacy.comicnarr.oprim_impl.subtitle import (
    build_comic_ass,
    build_srt_content,
    format_ass_time,
    format_srt_time,
    wrap_subtitle_text,
)
from hevi.layer4_legacy.comicnarr.oprim_impl.subtitle_ocr import (
    measure_subtitle_readability,
    text_similarity,
)
from hevi.layer4_legacy.comicnarr.oprim_impl.templates import (
    COMIC_STYLES,
    get_style_template,
)

__all__ = [
    "CAMERA_MOVES",
    "COMIC_STYLES",
    "ComicScene",
    "ComicScript",
    "ComicStyle",
    "apply_style_postprocess",
    "build_comic_ass",
    "build_ken_burns_filter",
    "build_srt_content",
    "format_ass_time",
    "format_srt_time",
    "get_style_template",
    "is_grayscale",
    "measure_subtitle_readability",
    "text_similarity",
    "wrap_subtitle_text",
]
