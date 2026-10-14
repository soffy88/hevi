"""M2 房间背景抽卡 (roomgacha) — CLI.

Usage:
    python -m hevi.manga.roomgacha.cli render --kind classroom --out /path/to/out
"""

from __future__ import annotations

import argparse
from pathlib import Path

from . import RoomSpec, SCENE_KINDS
from .render import render_room


def main() -> None:
    parser = argparse.ArgumentParser(description="M2 roomgacha: procedural 3D room background")
    parser.add_argument("--kind", choices=list(SCENE_KINDS), default="classroom")
    parser.add_argument("--seed", default="room-default")
    parser.add_argument("--messiness", type=float, default=0.3)
    parser.add_argument("--life", type=float, default=0.5)
    parser.add_argument("--azimuth", type=float, default=45.0)
    parser.add_argument("--elevation", type=float, default=45.0)
    parser.add_argument("--long-edge", type=int, default=2400)
    parser.add_argument("--solid-color", action="store_true")
    parser.add_argument("--duration", type=float, default=3.0)
    parser.add_argument("--fps", type=int, default=24)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    spec = RoomSpec(
        kind=args.kind,
        seed=args.seed,
        messiness=args.messiness,
        life=args.life,
        light_azimuth=args.azimuth,
        light_elevation=args.elevation,
        long_edge=args.long_edge,
        solid_color=args.solid_color,
    )
    res = render_room(spec, args.out, fps=args.fps, duration_s=args.duration)
    print(f"Rendered {spec.kind} -> {res['still']}")
    print(f"MP4: {res['mp4']}")
    print(f"GLB: {res['glb']}")


if __name__ == "__main__":
    main()
