"""hevi.watercolor — procedural (code) watercolour, deterministic and $0.

See :mod:`hevi.watercolor.core` for the algorithm.  Quick use::

    from hevi.watercolor import render_watercolor_image, demo_scene_shapes
    img = render_watercolor_image(demo_scene_shapes(640, 480),
                                  width=640, height=480, seed=42)

The registry-facing wrapper is ``image.watercolor_render``
(``hevi.capabilities.watercolor``).
"""

from hevi.watercolor.core import (
    DEFAULT_ALPHA,
    DEFAULT_DISPLACEMENT,
    DEFAULT_ITERATIONS,
    DEFAULT_LAYERS,
    base_points_for_shape,
    circle_points,
    demo_scene_shapes,
    displace_polygon,
    ellipse_points,
    parse_color,
    render_flat_image,
    render_watercolor_image,
    save_png,
)

__all__ = [
    "DEFAULT_ALPHA",
    "DEFAULT_DISPLACEMENT",
    "DEFAULT_ITERATIONS",
    "DEFAULT_LAYERS",
    "base_points_for_shape",
    "circle_points",
    "demo_scene_shapes",
    "displace_polygon",
    "ellipse_points",
    "parse_color",
    "render_flat_image",
    "render_watercolor_image",
    "save_png",
]
