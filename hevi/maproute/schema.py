"""Shot-table schema for the map-route line.

A *shot table* (镜头表) is the single input contract of ``video.map_route``.
Design note: the shape (an ordered list of stops, each with a camera move
and a narration segment) follows the shot-table idea popularised by
SpaceZephyr/map-motion (MIT License; see MAPROUTE.md) — no code is copied,
the schema below is an independent hevi design fitted to the capability
registry and to word-level alignment input.

Example::

    {
      "title": "京津冀南下之旅",
      "provider": "osm",               # osm | amap
      "profile": "driving",            # driving | walking | cycling
      "fps": 15,
      "stops": [
        {"name": "北京", "lat": 39.9087, "lon": 116.3974,
         "dwell_s": 3.0, "camera": "dive",
         "narration": "我们从北京出发"},
        {"name": "天津", "dwell_s": 4.0, "camera": "follow",
         "narration": "第一站来到天津"},
        {"name": "济南", "dwell_s": 4.0, "camera": "follow",
         "narration": "最后抵达济南"}
      ]
    }

* ``lat``/``lon`` are optional as a pair; stops without them are geocoded
  by name (gazetteer -> Photon -> Nominatim for the OSM provider, AMap
  geocoding for the amap provider).
* ``camera``: ``dive`` (俯冲: start pulled-back, push in while the leg is
  drawn), ``follow`` (跟随: viewport follows the route head), ``static``
  (全景固定).  A stop's camera describes the leg *arriving at* that stop;
  the first stop's camera describes the opening move.
* ``narration``: the spoken text segment belonging to this stop.  When a
  word-level alignment is supplied, the segment's end time in the
  alignment decides when the route has been drawn up to this stop.
"""

from __future__ import annotations

from typing import Any

from .errors import MapRouteError

CAMERA_MODES = ("dive", "follow", "static")
PROVIDERS = ("osm", "amap")
PROFILES = ("driving", "walking", "cycling")


def validate_shot_table(spec: Any) -> dict[str, Any]:
    """Validate + normalise a shot table; raise MapRouteError on problems."""
    if not isinstance(spec, dict):
        raise MapRouteError("shot table must be a JSON object")
    provider = str(spec.get("provider") or "osm").lower()
    if provider not in PROVIDERS:
        raise MapRouteError(
            f"shot table provider must be one of {PROVIDERS}, got {provider!r}"
        )
    profile = str(spec.get("profile") or "driving").lower()
    if profile not in PROFILES:
        raise MapRouteError(
            f"shot table profile must be one of {PROFILES}, got {profile!r}"
        )
    fps = spec.get("fps", 15)
    if not isinstance(fps, (int, float)) or isinstance(fps, bool) or not (5 <= fps <= 30):
        raise MapRouteError(f"shot table fps must be a number in [5, 30], got {fps!r}")

    raw_stops = spec.get("stops")
    if not isinstance(raw_stops, list) or len(raw_stops) < 2:
        raise MapRouteError("shot table needs a 'stops' list with at least 2 stops")
    if len(raw_stops) > 12:
        raise MapRouteError("shot table supports at most 12 stops")

    stops: list[dict[str, Any]] = []
    for idx, raw in enumerate(raw_stops):
        if not isinstance(raw, dict):
            raise MapRouteError(f"stop #{idx} must be an object")
        name = str(raw.get("name") or "").strip()
        if not name:
            raise MapRouteError(f"stop #{idx} needs a non-empty 'name'")
        lat, lon = raw.get("lat"), raw.get("lon")
        if (lat is None) != (lon is None):
            raise MapRouteError(
                f"stop {name!r}: 'lat' and 'lon' must be given together or not at all"
            )
        if lat is not None:
            if not isinstance(lat, (int, float)) or not (-90.0 <= float(lat) <= 90.0):
                raise MapRouteError(f"stop {name!r}: lat out of range: {lat!r}")
            if not isinstance(lon, (int, float)) or not (-180.0 <= float(lon) <= 180.0):
                raise MapRouteError(f"stop {name!r}: lon out of range: {lon!r}")
            lat, lon = float(lat), float(lon)
        dwell = raw.get("dwell_s", 3.0)
        if not isinstance(dwell, (int, float)) or isinstance(dwell, bool) or not (0.5 <= float(dwell) <= 30.0):
            raise MapRouteError(
                f"stop {name!r}: dwell_s must be a number in [0.5, 30], got {dwell!r}"
            )
        camera = str(raw.get("camera") or "follow").lower()
        if camera not in CAMERA_MODES:
            raise MapRouteError(
                f"stop {name!r}: camera must be one of {CAMERA_MODES}, got {camera!r}"
            )
        stops.append(
            {
                "name": name,
                "lat": lat,
                "lon": lon,
                "dwell_s": float(dwell),
                "camera": camera,
                "narration": str(raw.get("narration") or ""),
            }
        )

    polyline = spec.get("route_polyline")
    if polyline is not None:
        if not isinstance(polyline, list) or len(polyline) < 2:
            raise MapRouteError("route_polyline must be a list of >= 2 [lon, lat] pairs")
        cleaned: list[list[float]] = []
        for pt in polyline:
            if (
                not isinstance(pt, (list, tuple))
                or len(pt) != 2
                or not all(isinstance(v, (int, float)) for v in pt)
            ):
                raise MapRouteError("route_polyline points must be [lon, lat] numbers")
            cleaned.append([float(pt[0]), float(pt[1])])
        polyline = cleaned

    total = spec.get("total_duration_s")
    if total is not None:
        if not isinstance(total, (int, float)) or not (4.0 <= float(total) <= 600.0):
            raise MapRouteError(f"total_duration_s must be in [4, 600], got {total!r}")
        total = float(total)

    return {
        "title": str(spec.get("title") or "地图路线"),
        "provider": provider,
        "profile": profile,
        "fps": int(fps),
        "stops": stops,
        "route_polyline": polyline,
        "total_duration_s": total,
    }


__all__ = ["CAMERA_MODES", "PROVIDERS", "PROFILES", "validate_shot_table"]
