"""hevi.image.brushpaint — procedural brush-stroke painting engine.

Clean-room, zero-cost image route: a scene is a JSON spec of layered
field primitives (swirl sky, moon, hills, water, cypress, house,
meadow, clouds...); the engine samples the fields into a few thousand
seeded brush strokes and can render a finished still or a short video
of the painting painting itself.  Deterministic per (spec, seed).

Public surface:
    parse_scene / load_scene_file / get_template / list_templates
    build_strokes, render_still, render_paint_video
    pick_template_for_text  (storyfilm brush provider routing)
"""

from .engine import (
    Cell,
    Layer,
    Scene,
    SeededRng,
    Stroke,
    build_strokes,
)
from .render import render_paint_video, render_still
from .scene import (
    SpecError,
    get_template,
    list_templates,
    load_scene_file,
    parse_scene,
    pick_template_for_text,
)

__all__ = [
    "Cell",
    "Layer",
    "Scene",
    "SeededRng",
    "SpecError",
    "Stroke",
    "build_strokes",
    "get_template",
    "list_templates",
    "load_scene_file",
    "parse_scene",
    "pick_template_for_text",
    "render_paint_video",
    "render_still",
]
