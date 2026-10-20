"""Map-route line: narration-timestamp-driven real-map route animations.

See ``MAPROUTE.md`` next to this package for the line doc (shot-table
schema, provider switching, relation to the explainer line).
"""

from __future__ import annotations

from .errors import MapRouteError
from .render import render_map_route
from .schema import validate_shot_table
from .timeline import build_timeline, fraction_at, parse_alignment

__all__ = [
    "MapRouteError",
    "build_timeline",
    "fraction_at",
    "parse_alignment",
    "render_map_route",
    "validate_shot_table",
]
