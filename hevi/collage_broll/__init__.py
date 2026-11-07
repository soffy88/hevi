"""collage_broll: 半调纸拼贴 B-roll 产线。"""

from __future__ import annotations

__version__ = "0.1.0"

from .metaphor import generate_metaphor, generate_metaphors
from .spec import build_visual_spec
from .render import procedural_render
from .qa import run_qa

__all__ = [
    "generate_metaphor",
    "generate_metaphors",
    "build_visual_spec",
    "procedural_render",
    "run_qa",
]
