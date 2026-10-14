"""M3 OSM 实景街区 (locscout) — Overpass API client, caching, and terrain.

ODbL Notice: OpenStreetMap data is licensed under the Open Data Commons
Open Database License (ODbL) by the OpenStreetMap Foundation (OSMF).
Every output image includes the required attribution string:
"© OpenStreetMap contributors".
"""

from __future__ import annotations

import json
import math
import pathlib
import urllib.parse
import urllib.request
from typing import Any

from ..common import PRNG

PROXY_URL = "http://127.0.0.1:7890"
CACHE_DIR = pathlib.Path(__file__).resolve().parents[3] / "data" / "osm_cache"


def parse_location_input(loc_str_or_tuple: str | tuple[float, float]) -> tuple[float, float]:
    """Parse 'lat,lon' string, OSM/Google Maps URL, or float tuple."""
    if isinstance(loc_str_or_tuple, (tuple, list)):
        return float(loc_str_or_tuple[0]), float(loc_str_or_tuple[1])

    s = loc_str_or_tuple.strip()
    # Check for direct "lat,lon"
    if "," in s and not s.startswith("http"):
        parts = s.split(",")
        return float(parts[0].strip()), float(parts[1].strip())

    # Check for OpenStreetMap URL: e.g. ...#map=18/35.6614/139.6680 or ?lat=35.6614&lon=139.6680
    if "openstreetmap.org" in s:
        if "#map=" in s:
            frag = s.split("#map=")[1].split("&")[0]
            parts = frag.split("/")
            if len(parts) >= 3:
                return float(parts[1]), float(parts[2])
        if "lat=" in s and "lon=" in s:
            q = urllib.parse.parse_qs(urllib.parse.urlparse(s).query)
            return float(q["lat"][0]), float(q["lon"][0])

    # Check for Google Maps URL: .../@35.6614,139.6680,...
    if "google.com/maps" in s and "/@" in s:
        frag = s.split("/@")[1].split("/")[0]
        parts = frag.split(",")
        if len(parts) >= 2:
            return float(parts[0]), float(parts[1])

    raise ValueError(f"Cannot parse coordinates from location input: {s!r}")


def get_bbox(lat: float, lon: float, radius_m: float) -> tuple[float, float, float, float]:
    """Calculate (south, west, north, east) bounding box."""
    dlat = radius_m / 111320.0
    dlon = radius_m / (111320.0 * math.cos(math.radians(lat)))
    return (lat - dlat, lon - dlon, lat + dlat, lon + dlon)


def get_cache_path(lat: float, lon: float, radius_m: float) -> pathlib.Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"osm_{lat:.4f}_{lon:.4f}_{radius_m:.0f}.json"


def fetch_osm_data(lat: float, lon: float, radius_m: float = 250.0,
                   offline: bool = False) -> dict[str, Any]:
    """Fetch building/highway data from Overpass API via proxy, or read cache."""
    cache_path = get_cache_path(lat, lon, radius_m)
    if cache_path.exists():
        try:
            return json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception as e:
            if offline:
                raise RuntimeError(f"Corrupt OSM cache and offline mode: {e}")

    if offline:
        raise RuntimeError(f"OSM cache missing and offline: {cache_path}")

    s, w, n, e = get_bbox(lat, lon, radius_m)
    query = f"""[out:json][timeout:35];
(
  way["building"]({s:.5f},{w:.5f},{n:.5f},{e:.5f});
  way["highway"]({s:.5f},{w:.5f},{n:.5f},{e:.5f});
  way["waterway"]({s:.5f},{w:.5f},{n:.5f},{e:.5f});
);
out body;
>;
out skel qt;"""

    data = urllib.parse.urlencode({"data": query}).encode("utf-8")
    req = urllib.request.Request(
        "https://overpass-api.de/api/interpreter",
        data=data,
        headers={"User-Agent": "hevi-manga/1.0 (clean-room research)"},
    )

    proxy_handler = urllib.request.ProxyHandler({
        "http": PROXY_URL,
        "https": PROXY_URL,
    })
    opener = urllib.request.build_opener(proxy_handler)

    last_err: Exception | None = None
    for attempt in range(4):
        try:
            with opener.open(req, timeout=40) as resp:
                if resp.status == 200:
                    raw = resp.read()
                    doc = json.loads(raw)
                    if "elements" in doc:
                        cache_path.write_text(json.dumps(doc), encoding="utf-8")
                        return doc
        except Exception as ex:
            last_err = ex

    raise RuntimeError(
        f"Failed to fetch OSM data for ({lat:.4f}, {lon:.4f}) via Overpass API: {last_err}"
    )


# ---------------------------------------------------------------------------
# AWS Terrain Tiles (Terrarium)
# ---------------------------------------------------------------------------


def lat_lon_to_tile(lat: float, lon: float, z: int = 14) -> tuple[int, int, int]:
    x = int((lon + 180.0) / 360.0 * (1 << z))
    lat_rad = math.radians(lat)
    y = int((1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi) / 2.0 * (1 << z))
    return z, x, y


def get_elevation_sampler(lat: float, lon: float) -> Any:
    """Return an elevation function (lat, lon) -> meters using cached Terrarium tile."""
    z, x, y = lat_lon_to_tile(lat, lon, z=14)
    tile_path = CACHE_DIR / f"terrain_{z}_{x}_{y}.png"
    if not tile_path.exists():
        # Try fetching if online
        try:
            url = f"https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
            req = urllib.request.Request(url, headers={"User-Agent": "hevi-manga/1.0"})
            proxy_handler = urllib.request.ProxyHandler({"http": PROXY_URL, "https": PROXY_URL})
            opener = urllib.request.build_opener(proxy_handler)
            with opener.open(req, timeout=15) as resp:
                tile_path.write_bytes(resp.read())
        except Exception:
            pass

    if tile_path.exists():
        from PIL import Image
        img = Image.open(tile_path).convert("RGB")
        w, h = img.size

        # Bounds of this tile in lat/lon
        n = 1 << z
        lon_w = x / n * 360.0 - 180.0
        lon_e = (x + 1) / n * 360.0 - 180.0
        lat_n = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
        lat_s = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n))))

        def sample(plat: float, plon: float) -> float:
            px = int((plon - lon_w) / (lon_e - lon_w) * (w - 1))
            py = int((lat_n - plat) / (lat_n - lat_s) * (h - 1))
            px = max(0, min(w - 1, px))
            py = max(0, min(h - 1, py))
            r, g, b = img.getpixel((px, py))
            return (r * 256.0 + g + b / 256.0) - 32768.0

        return sample

    # Flat fallback
    return lambda plat, plon: 0.0
