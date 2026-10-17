"""M3 OSM 实景街区 (locscout) — 3D scene builder.

Converts OSM building ways and highways into 3D meshes (extruded building
footprints, road ribbons, white lines, trees, utility poles / 电线杆).
Sets camera at human eye height (1.55m).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from ..common import PRNG
from .osm import fetch_osm_data, get_elevation_sampler, parse_location_input


@dataclass
class LocationSpec:
    lat: float
    lon: float
    radius_m: float = 250.0
    time_of_day: str = "day"        # "day" | "evening"
    seed: str = "loc"
    long_edge: int = 1600
    camera_height: float = 1.55     # strictly human eye level
    camera_yaw: float = 0.0         # look direction (rad)
    camera_pitch: float = 0.05      # slight tilt
    orbit_speed: float = 0.1        # for dynamic video B-roll
    duration_s: float = 0.0         # 0 for still, >0 for video
    fps: int = 24
    offline: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "lat": self.lat,
            "lon": self.lon,
            "radius_m": self.radius_m,
            "time_of_day": self.time_of_day,
            "seed": self.seed,
            "long_edge": self.long_edge,
            "camera_height": self.camera_height,
            "camera_yaw": self.camera_yaw,
            "camera_pitch": self.camera_pitch,
            "orbit_speed": self.orbit_speed,
            "duration_s": self.duration_s,
            "fps": self.fps,
        }


def _calc_area_2d(pts: list[tuple[float, float]]) -> float:
    """Shoelace formula for 2D polygon area in m^2."""
    if len(pts) < 3:
        return 0.0
    area = 0.0
    n = len(pts)
    for i in range(n):
        j = (i + 1) % n
        area += pts[i][0] * pts[j][1]
        area -= pts[j][0] * pts[i][1]
    return abs(area) * 0.5


def _parse_height(tags: dict[str, str], area: float, rng: PRNG) -> float:
    """Building height: height tag > building:levels > area+use estimation with seed."""
    raw_h = tags.get("height")
    if raw_h:
        # e.g. "15m", "15.0", "15 m"
        s = raw_h.lower().replace("m", "").strip()
        try:
            val = float(s)
            if val > 0:
                return round(val, 2)
        except ValueError:
            pass

    levels = tags.get("building:levels")
    if levels:
        try:
            lvl = float(levels.strip())
            if lvl > 0:
                return round(lvl * 3.2, 2)
        except ValueError:
            pass

    # Estimation by use and area
    btype = tags.get("building", "yes")
    if btype in ("commercial", "retail", "office", "apartments", "hotel", "department_store"):
        base_h = 14.0 + (rng.next() * 14.0)
    elif btype in ("house", "residential", "detached", "terrace"):
        base_h = 6.0 + (rng.next() * 4.0)
    elif btype in ("school", "university", "civic", "hospital"):
        base_h = 10.0 + (rng.next() * 8.0)
    else:
        # Generic: scale slightly with footprint area
        base_h = 6.0 + min(18.0, area / 25.0) + (rng.next() * 4.0)

    return round(max(4.0, base_h), 2)


def build_location_scene(spec: LocationSpec) -> dict[str, Any]:
    """Parse cached/fetched OSM data into 3D scene description."""
    doc = fetch_osm_data(spec.lat, spec.lon, spec.radius_m, offline=spec.offline)
    elev_sampler = get_elevation_sampler(spec.lat, spec.lon)
    base_elev = elev_sampler(spec.lat, spec.lon)

    elements = doc.get("elements", [])
    nodes: dict[int, tuple[float, float]] = {}
    for el in elements:
        if el.get("type") == "node":
            nodes[el["id"]] = (el["lat"], el["lon"])

    lat0, lon0 = spec.lat, spec.lon
    m_per_deg_lat = 111320.0
    m_per_deg_lon = 111320.0 * math.cos(math.radians(lat0))

    def project(plat: float, plon: float) -> tuple[float, float, float]:
        x = (plon - lon0) * m_per_deg_lon
        z = -(plat - lat0) * m_per_deg_lat
        y = elev_sampler(plat, plon) - base_elev
        return round(x, 2), round(y, 2), round(z, 2)

    buildings: list[dict[str, Any]] = []
    roads: list[dict[str, Any]] = []
    poles: list[dict[str, Any]] = []
    trees: list[dict[str, Any]] = []

    rng = PRNG(spec.seed)
    seen_pole_coords: set[tuple[int, int]] = set()

    for el in elements:
        if el.get("type") != "way":
            continue
        tags = el.get("tags", {})
        way_nodes = [nodes[nid] for nid in el.get("nodes", []) if nid in nodes]
        if len(way_nodes) < 2:
            continue

        pts = [project(lat, lon) for lat, lon in way_nodes]

        # Buildings
        if "building" in tags:
            pts_2d = [(p[0], p[2]) for p in pts]
            area = _calc_area_2d(pts_2d)
            if area > 4.0:
                b_rng = PRNG(f"{spec.seed}_{el['id']}")
                h = _parse_height(tags, area, b_rng)
                # Compute centroid
                cx = sum(p[0] for p in pts[:-1]) / max(1, len(pts) - 1)
                cz = sum(p[2] for p in pts[:-1]) / max(1, len(pts) - 1)
                min_y = min(p[1] for p in pts)
                # Tone palette: subtle paper/concrete tones
                tone_val = round(0.75 + (b_rng.next() * 0.15), 3)
                buildings.append({
                    "id": el["id"],
                    "polygon": [[p[0], p[2]] for p in pts],
                    "base_y": min_y,
                    "height": h,
                    "centroid": [round(cx, 2), round(cz, 2)],
                    "color": [tone_val, tone_val, tone_val],
                })

        # Highways / Roads
        elif "highway" in tags:
            hw_type = tags.get("highway", "residential")
            width = 6.0 if hw_type in ("primary", "secondary", "tertiary") else 4.0
            roads.append({
                "id": el["id"],
                "points": pts,
                "width": width,
                "type": hw_type,
            })

            # Place utility poles (电线杆) and trees along the road
            cum_dist = 0.0
            for i in range(len(pts) - 1):
                p1, p2 = pts[i], pts[i + 1]
                dx = p2[0] - p1[0]
                dz = p2[2] - p1[2]
                seg_len = math.hypot(dx, dz)
                if seg_len < 1.0:
                    continue
                # Normal vector to side of road
                nx = -dz / seg_len
                nz = dx / seg_len

                # Poles every ~35m
                steps = max(1, int(seg_len / 35.0))
                for s in range(steps):
                    u = (s + 0.5) / steps
                    bx = p1[0] + dx * u + nx * (width * 0.5 + 0.8)
                    bz = p1[2] + dz * u + nz * (width * 0.5 + 0.8)
                    by = p1[1] + (p2[1] - p1[1]) * u
                    grid_key = (int(bx / 15.0), int(bz / 15.0))
                    if grid_key not in seen_pole_coords and math.hypot(bx, bz) < spec.radius_m * 0.9:
                        seen_pole_coords.add(grid_key)
                        poles.append({
                            "pos": [round(bx, 2), round(by, 2), round(bz, 2)],
                            "height": 7.5,
                            "rotY": round(math.atan2(dx, dz), 3),
                        })

                # Trees every ~25m on opposite side
                t_steps = max(1, int(seg_len / 25.0))
                for s in range(t_steps):
                    u = (s + 0.5) / t_steps
                    tx = p1[0] + dx * u - nx * (width * 0.5 + 1.2)
                    tz = p1[2] + dz * u - nz * (width * 0.5 + 1.2)
                    ty = p1[1] + (p2[1] - p1[1]) * u
                    if math.hypot(tx, tz) < spec.radius_m * 0.85:
                        scale = round(0.8 + rng.next() * 0.5, 2)
                        trees.append({
                            "pos": [round(tx, 2), round(ty, 2), round(tz, 2)],
                            "scale": scale,
                        })

    # Lighting depending on time of day
    if spec.time_of_day in ("evening", "sunset"):
        sun_color = [1.0, 0.65, 0.35]
        sun_azimuth = 245.0
        sun_elevation = 14.0
        sun_intensity = 0.95
        ambient_color = [0.85, 0.70, 0.60]
        ambient_intensity = 0.45
        sky_top = [0.95, 0.65, 0.45]
        sky_bottom = [0.98, 0.85, 0.70]
    else:
        sun_color = [1.0, 0.98, 0.92]
        sun_azimuth = 65.0
        sun_elevation = 48.0
        sun_intensity = 1.15
        ambient_color = [0.80, 0.82, 0.85]
        ambient_intensity = 0.55
        sky_top = [0.88, 0.92, 0.96]
        sky_bottom = [0.98, 0.98, 0.98]

    return {
        "spec": spec.to_dict(),
        "buildings": buildings,
        "roads": roads,
        "poles": poles[:80],      # capped for CPU performance
        "trees": trees[:120],
        "lighting": {
            "sun_color": sun_color,
            "sun_azimuth": sun_azimuth,
            "sun_elevation": sun_elevation,
            "sun_intensity": sun_intensity,
            "ambient_color": ambient_color,
            "ambient_intensity": ambient_intensity,
            "sky_top": sky_top,
            "sky_bottom": sky_bottom,
        },
    }
