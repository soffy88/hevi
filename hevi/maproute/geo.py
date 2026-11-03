"""Geocoding + routing for the map-route line (free, key-less by default).

Providers are pluggable via the shot table's ``provider`` field:

* ``osm`` (default, free, no key)
    - geocoding: built-in gazetteer for common Chinese cities first, then
      Photon (photon.komoot.io, OSM-based, no key), then Nominatim
      (nominatim.openstreetmap.org, proper User-Agent).  Host reachability
      measured 2026-10-20 from ubuntu26: Nominatim times out, Photon
      answers — hence the fallback order; both are attempted in code.
    - routing: OSRM public demo (router.project-osrm.org), real road
      geometry for driving / walking(f foot) / cycling(bike) profiles.
    - basemap tiles: Esri World Street Map (server.arcgisonline.com,
      free, key-less) — tile.openstreetmap.org times out from ubuntu26
      and CARTO basemaps serves API-key watermark placeholders
      (measured 2026-10-20).  See render.py.
* ``amap`` (高德, needs the user's own key in env ``HEVI_AMAP_KEY``)
    - geocoding: restapi.amap.com/v3/geocode/geo
    - routing: restapi.amap.com/v3/direction/{driving,walking,bicycling}
    - Without a key every amap call raises MapRouteError naming the env
      var and pointing at the free OSM default — never a silent fallback.

All HTTP goes through an injectable ``fetcher(url, headers) -> bytes`` so
the whole layer is unit-testable offline with canned responses.
"""

from __future__ import annotations

import json
import math
import os
import urllib.parse
import urllib.request
from typing import Any, Callable, Optional

from .errors import MapRouteError

Fetcher = Callable[[str, dict], bytes]

USER_AGENT = "hevi-maproute/1.0 (+https://github.com/soffy88; local research use)"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
PHOTON_URL = "https://photon.komoot.io/api/"
OSRM_URL = "https://router.project-osrm.org/route/v1"
AMAP_URL = "https://restapi.amap.com/v3"
AMAP_KEY_ENV = "HEVI_AMAP_KEY"

_OSRM_PROFILE = {"driving": "driving", "walking": "foot", "cycling": "bike"}
_AMAP_DIRECTION = {"driving": "driving", "walking": "walking", "cycling": "bicycling"}

# Built-in gazetteer (lon/lat, WGS-84) for frequent Chinese stops.  Checked
# before any network call, so well-known city tours render fully offline
# apart from routing/tiles.  Values are city-centre coordinates.
GAZETTEER: dict[str, tuple[float, float]] = {
    "北京": (116.4074, 39.9042), "北京市": (116.4074, 39.9042),
    "天津": (117.2008, 39.1252), "天津市": (117.2008, 39.1252),
    "石家庄": (114.5149, 37.8706), "济南": (117.1201, 36.6512),
    "上海": (121.4737, 31.2304), "上海市": (121.4737, 31.2304),
    "南京": (118.7969, 32.0603), "杭州": (120.1551, 30.2741),
    "西安": (108.9398, 34.3416), "成都": (104.0665, 30.5723),
    "重庆": (106.5516, 29.5630), "武汉": (114.3054, 30.5931),
    "长沙": (112.9388, 28.2282), "广州": (113.2644, 23.1291),
    "深圳": (114.0577, 22.5431), "郑州": (113.6254, 34.7466),
    "青岛": (120.3826, 36.0671), "大连": (121.6147, 38.9140),
    "沈阳": (123.4315, 41.8057), "哈尔滨": (126.5349, 45.8038),
    "昆明": (102.8329, 24.8801), "贵阳": (106.6302, 26.6470),
    "兰州": (103.8343, 36.0611), "乌鲁木齐": (87.6168, 43.8256),
    "拉萨": (91.1000, 29.6500), "合肥": (117.2830, 31.8612),
    "福州": (119.2965, 26.0745), "厦门": (118.0894, 24.4798),
    "香港": (114.1694, 22.3193), "台北": (121.5654, 25.0330),
    "呼和浩特": (111.7492, 40.8426), "太原": (112.5489, 37.8706),
    "西宁": (101.7782, 36.6171), "银川": (106.2309, 38.4872),
    "南昌": (115.8582, 28.6829), "南宁": (108.3665, 22.8170),
    "海口": (110.1983, 20.0440), "大理": (100.2676, 25.6065),
}


def default_fetcher(url: str, headers: dict | None = None, timeout: float = 20.0) -> bytes:
    req = urllib.request.Request(url, headers=headers or {"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - fixed hosts
        return resp.read()


def _fetch_json(fetcher: Fetcher, url: str) -> Any:
    raw = fetcher(url, {"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        return json.loads(raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else raw)
    except Exception as exc:
        raise MapRouteError(f"bad JSON from {url.split('?')[0]}: {exc}") from exc


def amap_key() -> str:
    return os.getenv(AMAP_KEY_ENV, "").strip()


def require_amap_key() -> str:
    key = amap_key()
    if not key:
        raise MapRouteError(
            f"provider 'amap' needs env {AMAP_KEY_ENV} (高德开放平台 Web服务 key, "
            "user-provided). No key set: use provider 'osm' (default) for the "
            "free key-less OSM/Photon/OSRM/CARTO stack instead."
        )
    return key


# ---------------------------------------------------------------- geocoding

def geocode_place(
    name: str,
    *,
    provider: str = "osm",
    fetcher: Optional[Fetcher] = None,
) -> dict[str, Any]:
    """Resolve a place name to {lon, lat, source, display_name}."""
    fetcher = fetcher or default_fetcher
    if provider == "amap":
        return _geocode_amap(name, fetcher=fetcher)
    if provider != "osm":
        raise MapRouteError(f"unknown geocode provider: {provider!r}")
    hit = GAZETTEER.get(name.strip())
    if hit is not None:
        return {"lon": hit[0], "lat": hit[1], "source": "gazetteer", "display_name": name}
    errors: list[str] = []
    # Photon first (reachable from ubuntu26), Nominatim second (canonical
    # OSM geocoder; times out from ubuntu26 as of 2026-10-20 but is correct
    # on hosts that can reach it).
    for fn in (_geocode_photon, _geocode_nominatim):
        try:
            return fn(name, fetcher=fetcher)
        except MapRouteError as exc:
            errors.append(str(exc))
    raise MapRouteError(f"geocoding failed for {name!r}: " + " | ".join(errors))


def _geocode_photon(name: str, *, fetcher: Fetcher) -> dict[str, Any]:
    url = PHOTON_URL + "?" + urllib.parse.urlencode({"q": name, "limit": 1, "lang": "zh"})
    data = _fetch_json(fetcher, url)
    feats = data.get("features") or []
    if not feats:
        raise MapRouteError(f"photon: no result for {name!r}")
    coords = feats[0]["geometry"]["coordinates"]
    props = feats[0].get("properties") or {}
    return {
        "lon": float(coords[0]),
        "lat": float(coords[1]),
        "source": "photon",
        "display_name": str(props.get("name") or name),
    }


def _geocode_nominatim(name: str, *, fetcher: Fetcher) -> dict[str, Any]:
    url = NOMINATIM_URL + "?" + urllib.parse.urlencode(
        {"q": name, "format": "jsonv2", "limit": 1}
    )
    data = _fetch_json(fetcher, url)
    if not data:
        raise MapRouteError(f"nominatim: no result for {name!r}")
    return {
        "lon": float(data[0]["lon"]),
        "lat": float(data[0]["lat"]),
        "source": "nominatim",
        "display_name": str(data[0].get("display_name") or name),
    }


def _geocode_amap(name: str, *, fetcher: Fetcher) -> dict[str, Any]:
    key = require_amap_key()
    url = AMAP_URL + "/geocode/geo?" + urllib.parse.urlencode(
        {"key": key, "address": name}
    )
    data = _fetch_json(fetcher, url)
    geocodes = data.get("geocodes") or []
    if str(data.get("status")) != "1" or not geocodes:
        raise MapRouteError(
            f"amap geocode failed for {name!r}: {data.get('info') or data.get('infocode')}"
        )
    lon_s, lat_s = str(geocodes[0]["location"]).split(",")
    return {
        "lon": float(lon_s),
        "lat": float(lat_s),
        "source": "amap",
        "display_name": str(geocodes[0].get("formatted_address") or name),
    }


# ------------------------------------------------------------------ routing

def fetch_route(
    coords: list[tuple[float, float]],
    *,
    provider: str = "osm",
    profile: str = "driving",
    fetcher: Optional[Fetcher] = None,
) -> dict[str, Any]:
    """Route through (lon, lat) waypoints -> {polyline, distance_m, duration_s, source}.

    polyline is a list of [lon, lat] pairs (GeoJSON order), dense enough to
    draw.  Amap coordinates are GCJ-02 while OSM/OSRM are WGS-84; mixing is
    the caller's responsibility — the shot table's provider applies to the
    whole table so a render never mixes the two silently per-stop.
    """
    fetcher = fetcher or default_fetcher
    if len(coords) < 2:
        raise MapRouteError("routing needs at least 2 waypoints")
    if provider == "amap":
        return _route_amap(coords, profile=profile, fetcher=fetcher)
    if provider != "osm":
        raise MapRouteError(f"unknown route provider: {provider!r}")
    return _route_osrm(coords, profile=profile, fetcher=fetcher)


def _route_osrm(
    coords: list[tuple[float, float]], *, profile: str, fetcher: Fetcher
) -> dict[str, Any]:
    osrm_profile = _OSRM_PROFILE.get(profile, "driving")
    joined = ";".join(f"{lon:.6f},{lat:.6f}" for lon, lat in coords)
    url = (
        f"{OSRM_URL}/{osrm_profile}/{joined}"
        "?overview=full&geometries=geojson&steps=false"
    )
    data = _fetch_json(fetcher, url)
    routes = data.get("routes") or []
    if data.get("code") != "Ok" or not routes:
        raise MapRouteError(f"osrm route failed: code={data.get('code')!r}")
    route = routes[0]
    polyline = [[float(x), float(y)] for x, y in route["geometry"]["coordinates"]]
    return {
        "polyline": polyline,
        "distance_m": float(route.get("distance") or 0.0),
        "duration_s": float(route.get("duration") or 0.0),
        "source": "osrm",
    }


def _route_amap(
    coords: list[tuple[float, float]], *, profile: str, fetcher: Fetcher
) -> dict[str, Any]:
    key = require_amap_key()
    mode = _AMAP_DIRECTION.get(profile, "driving")
    origin = f"{coords[0][0]:.6f},{coords[0][1]:.6f}"
    destination = f"{coords[-1][0]:.6f},{coords[-1][1]:.6f}"
    params: dict[str, str] = {"key": key, "origin": origin, "destination": destination}
    if len(coords) > 2:
        params["waypoints"] = ";".join(f"{lon:.6f},{lat:.6f}" for lon, lat in coords[1:-1])
    url = f"{AMAP_URL}/direction/{mode}?" + urllib.parse.urlencode(params)
    data = _fetch_json(fetcher, url)
    route = data.get("route") or {}
    paths = route.get("paths") or []
    if str(data.get("status")) != "1" or not paths:
        raise MapRouteError(
            f"amap route failed: {data.get('info') or data.get('infocode')}"
        )
    path = paths[0]
    polyline: list[list[float]] = []
    for step in path.get("steps") or []:
        for pair in str(step.get("polyline") or "").split(";"):
            if "," in pair:
                lon_s, lat_s = pair.split(",", 1)
                polyline.append([float(lon_s), float(lat_s)])
    if len(polyline) < 2:
        raise MapRouteError("amap route returned an empty polyline")
    return {
        "polyline": polyline,
        "distance_m": float(path.get("distance") or 0.0),
        "duration_s": float(path.get("duration") or 0.0),
        "source": "amap",
    }


# ------------------------------------------------------------- geo math

def haversine_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Great-circle distance between (lon, lat) pairs, metres."""
    lon1, lat1 = math.radians(a[0]), math.radians(a[1])
    lon2, lat2 = math.radians(b[0]), math.radians(b[1])
    dlon, dlat = lon2 - lon1, lat2 - lat1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * 6371000.0 * math.asin(math.sqrt(h))


def cumulative_fractions(polyline: list[list[float]]) -> list[float]:
    """Cumulative distance fraction (0..1) at each polyline vertex."""
    total = 0.0
    dists = [0.0]
    for i in range(1, len(polyline)):
        total += haversine_m(
            (polyline[i - 1][0], polyline[i - 1][1]), (polyline[i][0], polyline[i][1])
        )
        dists.append(total)
    if total <= 0:
        raise MapRouteError("route polyline has zero length")
    return [d / total for d in dists]


def fraction_at_point(
    polyline: list[list[float]], fractions: list[float], lon: float, lat: float
) -> float:
    """Route fraction of the polyline vertex nearest to (lon, lat)."""
    best_i, best_d = 0, float("inf")
    for i, (x, y) in enumerate(polyline):
        d = (x - lon) ** 2 + (y - lat) ** 2
        if d < best_d:
            best_d, best_i = d, i
    return fractions[best_i]


def point_at_fraction(
    polyline: list[list[float]], fractions: list[float], frac: float
) -> tuple[float, float]:
    """Interpolated (lon, lat) at route fraction ``frac`` (clamped 0..1)."""
    frac = min(1.0, max(0.0, frac))
    for i in range(1, len(fractions)):
        if fractions[i] >= frac:
            lo, hi = fractions[i - 1], fractions[i]
            span = hi - lo
            t = 0.0 if span <= 0 else (frac - lo) / span
            x = polyline[i - 1][0] + (polyline[i][0] - polyline[i - 1][0]) * t
            y = polyline[i - 1][1] + (polyline[i][1] - polyline[i - 1][1]) * t
            return (x, y)
    return (polyline[-1][0], polyline[-1][1])


# Web-Mercator world-pixel projection (slippy map), used for tile stitching.
def latlon_to_world_px(lat: float, lon: float, zoom: int) -> tuple[float, float]:
    size = 256.0 * (2**zoom)
    x = (lon + 180.0) / 360.0 * size
    lat_c = max(-85.05112878, min(85.05112878, lat))
    rad = math.radians(lat_c)
    y = (1.0 - math.log(math.tan(rad) + 1.0 / math.cos(rad)) / math.pi) / 2.0 * size
    return (x, y)


__all__ = [
    "AMAP_KEY_ENV",
    "GAZETTEER",
    "USER_AGENT",
    "amap_key",
    "cumulative_fractions",
    "default_fetcher",
    "fetch_route",
    "fraction_at_point",
    "geocode_place",
    "haversine_m",
    "latlon_to_world_px",
    "point_at_fraction",
    "require_amap_key",
]
