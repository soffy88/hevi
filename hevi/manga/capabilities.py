"""M4 Hevi unified capability registrations for manga unit.

Registers:
  - manga.name_layout: Storyboard breaker -> manga panel layout JSON + SVG + PNG (+ optional mp4)
  - manga.room_bg: Procedural 3D room background (classroom, own_room, living_room)
  - manga.location_bg: OSM real-world street manga background (human-eye 1.55m camera + ODbL attribution)
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from ..capabilities.registry import Capability, CapabilityResult, register
from ..manga.common import sha256_file
from ..manga.locscout import LocationSpec, parse_location_input, render_location
from ..manga.namegen.cli import run as run_namegen
from ..manga.roomgacha import RoomSpec, render_room

_FFMPEG = "/home/soffy/.local/bin/ffmpeg"


def _render_name_layout(
    params: dict[str, Any],
    out_dir: Path,
    *,
    duration: float = 2.0,
    aspect: str = "9:16",
    seed: str = "name_seed",
) -> CapabilityResult:
    doc = {
        "title": params.get("title", "Storyboard"),
        "characters": params.get("characters", []),
        "beats": params.get("beats", []),
    }
    reading_dir = params.get("reading_direction", "rtl")
    variation = float(params.get("variation", 0.3))

    res = run_namegen(doc, aspect=aspect, reading_direction=reading_dir, seed=seed,
                      variation=variation, out_dir=out_dir)
    png_path = Path(res["png"])

    # If duration > 0, produce a video slideshow / preview so capability passes ffprobe video check
    mp4_path = None
    if duration > 0:
        mp4_path = out_dir / "storyboard_preview.mp4"
        cmd = [
            _FFMPEG, "-y",
            "-loop", "1",
            "-i", str(png_path),
            "-c:v", "libx264",
            "-t", str(duration),
            "-pix_fmt", "yuv420p",
            "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
            "-movflags", "+faststart",
            str(mp4_path),
        ]
        subprocess.run(cmd, check=True, capture_output=True)

    h = sha256_file(mp4_path if mp4_path else png_path)
    return CapabilityResult(
        mp4=str(mp4_path) if mp4_path else None,
        png=str(png_path),
        duration=duration if mp4_path else 0.0,
        sha256=h,
        qa=res["report"],
    )


def _render_room_bg(
    params: dict[str, Any],
    out_dir: Path,
    *,
    duration: float = 2.0,
    aspect: str = "16:9",
    seed: str = "room_seed",
) -> CapabilityResult:
    spec = RoomSpec(
        kind=params["kind"],
        seed=seed,
        messiness=float(params.get("messiness", 0.3)),
        life=float(params.get("life", 0.5)),
        light_azimuth=float(params.get("light_azimuth", 45.0)),
        light_elevation=float(params.get("light_elevation", 45.0)),
        solid_color=bool(params.get("solid_color", False)),
        long_edge=int(params.get("long_edge", 1280)),
    )
    # Set aspect hint
    spec_dict = spec.to_dict()
    spec_dict["aspect"] = aspect

    res = render_room(spec, out_dir, fps=24, duration_s=duration)
    mp4_path = res.get("mp4")
    png_path = res.get("still")
    h = sha256_file(mp4_path if mp4_path else png_path)
    return CapabilityResult(
        mp4=str(mp4_path) if mp4_path else None,
        png=str(png_path),
        duration=duration,
        sha256=h,
        qa=res["report"],
    )


def _render_location_bg(
    params: dict[str, Any],
    out_dir: Path,
    *,
    duration: float = 2.0,
    aspect: str = "16:9",
    seed: str = "loc_seed",
) -> CapabilityResult:
    lat, lon = parse_location_input(params["location"])
    spec = LocationSpec(
        lat=lat,
        lon=lon,
        radius_m=float(params.get("radius_m", 250.0)),
        time_of_day="evening" if params.get("time_of_day") in ("evening", "sunset") else "day",
        seed=seed,
        long_edge=int(params.get("long_edge", 1280)),
        duration_s=duration,
        offline=bool(params.get("offline", False)),
    )
    res = render_location(spec, out_dir, fps=24, duration_s=duration)
    mp4_path = res.get("mp4")
    png_path = res.get("still")
    h = sha256_file(mp4_path if mp4_path else png_path)
    return CapabilityResult(
        mp4=str(mp4_path) if mp4_path else None,
        png=str(png_path),
        duration=duration,
        sha256=h,
        qa=res["report"],
    )


def register_manga_capabilities() -> None:
    # 1. manga.name_layout
    register(
        Capability(
            name="manga.name_layout",
            kind="shot",
            aspects=["9:16", "B5", "1:1", "4:5", "16:9"],
            params_schema={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "characters": {"type": "array", "items": {"type": "string"}},
                    "beats": {"type": "array"},
                    "reading_direction": {"type": "string", "enum": ["rtl", "ltr"]},
                    "variation": {"type": "number"},
                },
                "required": ["beats"],
            },
            cpu_cost_hint=0.1,
            render_fn=_render_name_layout,
        )
    )

    # 2. manga.room_bg
    register(
        Capability(
            name="manga.room_bg",
            kind="shot",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": ["classroom", "own_room", "living_room"]},
                    "messiness": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                    "life": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                    "light_azimuth": {"type": "number"},
                    "light_elevation": {"type": "number"},
                    "solid_color": {"type": "boolean"},
                    "long_edge": {"type": "integer"},
                },
                "required": ["kind"],
            },
            cpu_cost_hint=1.2,
            render_fn=_render_room_bg,
        )
    )

    # 3. manga.location_bg
    register(
        Capability(
            name="manga.location_bg",
            kind="shot",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "location": {"type": "string"},
                    "radius_m": {"type": "number"},
                    "time_of_day": {"type": "string", "enum": ["day", "evening", "sunset"]},
                    "long_edge": {"type": "integer"},
                    "offline": {"type": "boolean"},
                },
                "required": ["location"],
            },
            cpu_cost_hint=1.5,
            render_fn=_render_location_bg,
        )
    )
