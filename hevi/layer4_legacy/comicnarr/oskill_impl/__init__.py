"""Comic narration skills."""

from hevi.layer4_legacy.comicnarr.oskill_impl.prompt_builder import (
    build_scene_prompt,
)
from hevi.layer4_legacy.comicnarr.oskill_impl.script_planner import (
    FALLBACK_SCRIPTS,
    generate_comic_script,
)

__all__ = [
    "FALLBACK_SCRIPTS",
    "build_scene_prompt",
    "generate_comic_script",
]
