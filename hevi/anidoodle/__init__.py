"""anidoodle code-drawn style library (S29).

The engine is vendored under ``third_party/anidoodle`` (Apache-2.0, see that
directory's LICENSE/NOTICE).  This package never invents a success: when Node,
the engine, the browser or a gate is missing it raises a capability error and
says which precondition failed.
"""

from __future__ import annotations

from . import soundpack
from .bgm import compose_for_duration
from .catalog import (
    StyleInfo,
    families,
    get_style,
    list_styles,
    recommend_style,
    validation_for,
)
from .engine import AnidoodleError, EngineInfo, engine_info
from .gates import check_safe_area, run_gate, run_verify_export
from .music import compose_bgm
from .render import (
    render_draw_clip,
    render_gallery,
    render_partial,
    render_still,
)

__all__ = [
    "AnidoodleError",
    "EngineInfo",
    "StyleInfo",
    "check_safe_area",
    "compose_bgm",
    "compose_for_duration",
    "engine_info",
    "families",
    "get_style",
    "list_styles",
    "recommend_style",
    "render_draw_clip",
    "render_gallery",
    "render_partial",
    "render_still",
    "run_gate",
    "run_verify_export",
    "soundpack",
    "validation_for",
]
