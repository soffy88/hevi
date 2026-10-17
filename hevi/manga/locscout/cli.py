"""M3 OSM 实景街区 (locscout) — CLI.

Usage:
    python -m hevi.manga.locscout.cli render --loc "35.6614,139.6680" --time-of-day day --out /path/to/out
"""

from __future__ import annotations

import argparse
from pathlib import Path

from .builder import LocationSpec
from .osm import parse_location_input
from .render import render_location


def main() -> None:
    parser = argparse.ArgumentParser(description="M3 locscout: OSM real-world street manga background")
    parser.add_argument("--loc", required=True, help="lat,lon or OSM/Google Maps URL")
    parser.add_argument("--radius", type=float, default=250.0)
    parser.add_argument("--time-of-day", choices=["day", "evening", "sunset"], default="day")
    parser.add_argument("--seed", default="loc-default")
    parser.add_argument("--long-edge", type=int, default=1600)
    parser.add_argument("--duration", type=float, default=0.0)
    parser.add_argument("--fps", type=int, default=24)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    lat, lon = parse_location_input(args.loc)
    spec = LocationSpec(
        lat=lat,
        lon=lon,
        radius_m=args.radius,
        time_of_day="evening" if args.time_of_day in ("evening", "sunset") else "day",
        seed=args.seed,
        long_edge=args.long_edge,
        duration_s=args.duration,
        fps=args.fps,
        offline=args.offline,
    )
    res = render_location(spec, args.out)
    print(f"Rendered {spec.time_of_day} street -> {res['still']}")
    if res["mp4"]:
        print(f"MP4: {res['mp4']}")
    print(f"Attribution OK: {res['report']['attribution_present']}")


if __name__ == "__main__":
    main()
