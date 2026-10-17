"""M3 OSM 实景街区 (locscout) — package exports."""

from .builder import LocationSpec, build_location_scene
from .osm import fetch_osm_data, parse_location_input
from .render import (
    render_location,
    stamp_osm_attribution,
    check_attribution_pixels_exist,
    OSM_ATTRIBUTION_TEXT,
)

__all__ = [
    "LocationSpec",
    "build_location_scene",
    "fetch_osm_data",
    "parse_location_input",
    "OSM_ATTRIBUTION_TEXT",
    "render_location",
    "stamp_osm_attribution",
    "check_attribution_pixels_exist",
]
