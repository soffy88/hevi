"""hevi.image.genart — seeded generative art (flow fields + fractals).

Offline, zero-cost route for abstract visuals: title backgrounds,
atmosphere loops, poster art, music-visualisation beds.  A spec
(seed, palette, algorithm, density) fully determines the output --
same spec, same pixels, every run.

Conceptual sibling of Anthropic's ``algorithmic-art`` skill
(Apache-2.0, archived under ``~/workspace/references/algorithmic-art``
and installed in the Claude/Codex skill dirs); this engine is an
original numpy/PIL implementation, not a port of the p5.js code.

Public surface:
    parse_spec / GenartSpec / SpecError / resolve_palette / PALETTES
    simulate_flowfield, julia_mu
    render_still, render_video, render_flow_frame, render_julia_frame
"""

from .engine import (
    PALETTES,
    FlowField,
    GenartSpec,
    Palette,
    SpecError,
    julia_mu,
    parse_spec,
    resolve_palette,
    simulate_flowfield,
)
from .render import (
    loop_life,
    render_flow_frame,
    render_julia_frame,
    render_still,
    render_video,
)

__all__ = [
    "PALETTES",
    "FlowField",
    "GenartSpec",
    "Palette",
    "SpecError",
    "julia_mu",
    "loop_life",
    "parse_spec",
    "render_flow_frame",
    "render_julia_frame",
    "render_still",
    "render_video",
    "resolve_palette",
    "simulate_flowfield",
]
