"""Map-route capability: narration-driven real-map route animations.

Registers ``video.map_route`` (CAPABILITY_CONTRACT.md; precedent:
``.pixstag`` / ``.earshot_gate``).  The capability takes a shot table
(ordered stops + camera moves + per-stop narration), geocodes the stops,
fetches a real route, drives route progress from word-level alignment
timestamps when supplied, renders frames in headless Chromium over real
basemap tiles, and encodes an MP4 with ffmpeg.  Full line doc:
``hevi/maproute/MAPROUTE.md``.

Cost: free.  The default OSM stack (gazetteer / Photon / Nominatim
geocoding, OSRM routing, Esri World Street Map tiles) needs no key and makes no
paid calls.  Provider ``amap`` instead reads the user's own key from env
``HEVI_AMAP_KEY`` and raises CapabilityError when it is missing.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

_COST_NOTE = (
    "Free: default OSM stack (Photon/Nominatim geocoding, OSRM routing, "
    "Esri tiles) is key-less and unpaid. Provider 'amap' uses the user's "
    "own HEVI_AMAP_KEY (Amap free quota). Local cost is Chromium frame "
    "capture + ffmpeg only."
)

_STOP_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "minLength": 1},
        "lat": {"type": "number", "minimum": -90, "maximum": 90},
        "lon": {"type": "number", "minimum": -180, "maximum": 180},
        "dwell_s": {"type": "number", "minimum": 0.5, "maximum": 30, "default": 3},
        "camera": {"type": "string", "enum": ["dive", "follow", "static"], "default": "follow"},
        "narration": {"type": "string", "default": ""},
    },
    "required": ["name"],
    "additionalProperties": False,
}


def _render_map_route(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    from hevi.maproute.render import render_map_route
    from hevi.maproute.errors import MapRouteError

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    shot_table = params.get("shot_table") or {
        k: params[k]
        for k in ("title", "provider", "profile", "fps", "stops", "route_polyline", "total_duration_s")
        if k in params
    }

    alignment = params.get("alignment")
    alignment_path = params.get("alignment_path")
    if alignment is None and alignment_path:
        try:
            alignment = json.loads(Path(str(alignment_path)).read_text(encoding="utf-8"))
        except Exception as exc:
            raise CapabilityError(
                f"video.map_route: cannot read alignment_path {alignment_path!r}: {exc}"
            ) from exc

    try:
        result = render_map_route(
            shot_table, out_dir, aspect=aspect, alignment=alignment
        )
    except MapRouteError as exc:
        raise CapabilityError(f"video.map_route: {exc}") from exc
    except Exception as exc:  # noqa: BLE001 - contract wants CapabilityError
        raise CapabilityError(f"video.map_route failed: {exc}") from exc

    mp4 = Path(result["mp4"])
    sidecar = result["sidecar"]
    return CapabilityResult(
        mp4=str(mp4),
        duration_s=float(result["duration_s"]),
        sha256=compute_sha256(mp4),
        qa={
            "timeline_mode": sidecar["timeline"]["mode"],
            "route_source": sidecar["route"]["source"],
            "route_distance_km": round(sidecar["route"]["distance_m"] / 1000.0, 1),
            "basemap_source": sidecar["basemap"]["source"],
            "engine": sidecar["engine"],
            "frames": sidecar["frames"],
            "sidecar_json": str(out_dir / "maproute_sidecar.json"),
            "note": _COST_NOTE,
        },
    )


def register_maproute_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True

    register(
        Capability(
            name="video.map_route",
            kind="shot",
            aspects=["16:9", "9:16", "1:1"],
            params_schema={
                "type": "object",
                "properties": {
                    "shot_table": {
                        "type": "object",
                        "description": "Shot table (see stops/provider/... below); "
                        "may also be given inline as top-level params.",
                    },
                    "title": {"type": "string", "default": "地图路线"},
                    "provider": {
                        "type": "string",
                        "enum": ["osm", "amap"],
                        "default": "osm",
                        "description": "osm = free key-less stack; amap needs HEVI_AMAP_KEY",
                    },
                    "profile": {
                        "type": "string",
                        "enum": ["driving", "walking", "cycling"],
                        "default": "driving",
                    },
                    "fps": {"type": "integer", "minimum": 5, "maximum": 30, "default": 15},
                    "stops": {
                        "type": "array",
                        "items": _STOP_SCHEMA,
                        "minItems": 2,
                        "maxItems": 12,
                    },
                    "route_polyline": {
                        "type": "array",
                        "items": {
                            "type": "array",
                            "items": {"type": "number"},
                            "minItems": 2,
                            "maxItems": 2,
                        },
                        "minItems": 2,
                        "description": "Optional bring-your-own route geometry "
                        "[[lon, lat], ...]; skips the routing engine.",
                    },
                    "total_duration_s": {"type": "number", "minimum": 4, "maximum": 600},
                    "alignment": {
                        "type": "object",
                        "description": "Word-level alignment artefact "
                        "({words: [{text, start_ms, end_ms}]}) as produced by "
                        "hevi whisper_local / forced alignment; per-stop "
                        "narration segment end times drive route progress.",
                    },
                    "alignment_path": {
                        "type": "string",
                        "description": "Path to an alignment JSON file "
                        "(e.g. output/storyfilm/<film>/alignment.json).",
                    },
                },
                "additionalProperties": False,
            },
            cpu_cost_hint=2.0,  # chromium screenshots dominate; no cloud cost
            render=_render_map_route,
            description=(
                "Map-route film (地图路线片): shot table of ordered stops -> "
                "geocode (gazetteer/Photon/Nominatim or AMap) -> real route "
                "(OSRM or AMap) -> route drawn progressively over real Esri "
                "World Street Map basemap tiles in headless Chromium -> MP4. Route "
                "progress is driven by word-level narration alignment "
                "timestamps when supplied (each stop's narration segment end "
                "= arrival at that stop), otherwise by per-stop dwell "
                "seconds. Camera moves: dive / follow / static. Free: no key "
                "and no paid calls on the default OSM provider; provider "
                "'amap' requires the user's HEVI_AMAP_KEY."
            ),
            line="maproute",
        )
    )
    return ["video.map_route"]
