"""CLI for the brush painting engine (same level as storyfilm.oneclick).

Usage:
    python -m hevi.image.brushpaint templates
    python -m hevi.image.brushpaint still --template pond_night -o pond.png
    python -m hevi.image.brushpaint still --scene scene.json -o out.png --progress 0.6
    python -m hevi.image.brushpaint paint --template pond_night -o pond.mp4 --seconds 24

Sizes: --size WxH wins; otherwise --aspect picks 720x1280 / 1280x720 /
960x960.  Everything is local CPU work: no keys, no network, $0.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from .render import render_paint_video, render_still
from .scene import get_template, list_templates, load_scene_file, parse_scene

_ASPECT_SIZE = {"9:16": (720, 1280), "16:9": (1280, 720), "1:1": (960, 960)}


def _resolve_size(args: argparse.Namespace) -> tuple[int, int]:
    if args.size:
        try:
            w, h = args.size.lower().split("x")
            return int(w), int(h)
        except ValueError:
            raise SystemExit(f"--size must look like 720x1280, got {args.size!r}")
    return _ASPECT_SIZE[args.aspect]


def _load_scene(args: argparse.Namespace):
    if args.scene:
        spec, scene = load_scene_file(args.scene)
    else:
        spec = get_template(args.template)
        scene = parse_scene(spec)
    if args.seed is not None:
        scene.seed = args.seed
        spec = {**spec, "seed": args.seed}
    return spec, scene


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hevi.image.brushpaint", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("templates", help="list bundled scene templates")

    for name in ("still", "paint"):
        p = sub.add_parser(name)
        src = p.add_mutually_exclusive_group()
        src.add_argument("--scene", help="scene JSON file")
        src.add_argument("--template", default="pond_night",
                         help=f"bundled template (one of {list_templates()})")
        p.add_argument("-o", "--out", required=True, help="output file")
        p.add_argument("--aspect", default="9:16", choices=sorted(_ASPECT_SIZE))
        p.add_argument("--size", help="explicit WxH, overrides --aspect")
        p.add_argument("--seed", type=int, help="override the scene seed")
        if name == "still":
            p.add_argument("--progress", type=float, default=1.0,
                           help="reveal progress 0..1 (default 1 = finished painting)")
        else:
            p.add_argument("--seconds", type=float, default=20.0)
            p.add_argument("--fps", type=int, default=12)

    args = parser.parse_args(argv)

    if args.cmd == "templates":
        for name in list_templates():
            print(name)
        return 0

    spec, scene = _load_scene(args)
    width, height = _resolve_size(args)
    started = time.perf_counter()
    if args.cmd == "still":
        img = render_still(scene, width, height, progress=args.progress)
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        img.save(out)
        from .engine import build_strokes

        print(json.dumps({
            "png": str(out),
            "template_or_scene": spec.get("name"),
            "size": f"{width}x{height}",
            "progress": args.progress,
            "strokes_total": len(build_strokes(scene, width, height)),
            "render_seconds": round(time.perf_counter() - started, 2),
            "cost": 0.0,
        }, ensure_ascii=False))
        return 0

    stats = render_paint_video(
        scene, args.out, width, height, seconds=args.seconds, fps=args.fps
    )
    stats.update({
        "template_or_scene": spec.get("name"),
        "size": f"{width}x{height}",
        "cost": 0.0,
    })
    print(json.dumps(stats, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
