"""CLI for the generative-art engine.

Examples:
    python -m hevi.image.genart --algorithm flowfield --seed 7 \\
        --palette abyss --mode still --out /tmp/flow.png
    python -m hevi.image.genart --algorithm flowfield --seed 42 \\
        --mode video --seconds 10 --out /tmp/flow.mp4
    python -m hevi.image.genart --algorithm julia --seed 3 \\
        --palette ember --mode still --out /tmp/julia.png

Prints a one-line JSON summary (paths, sha256, timings, cost 0.0).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from .engine import parse_spec
from .render import render_still, render_video

_ASPECT_SIZE = {"16:9": (1280, 720), "9:16": (720, 1280), "1:1": (960, 960)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="hevi.image.genart")
    ap.add_argument("--algorithm", default="flowfield", choices=["flowfield", "julia"])
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--palette", default="abyss")
    ap.add_argument("--mode", default="still", choices=["still", "video"])
    ap.add_argument("--aspect", default="16:9", choices=sorted(_ASPECT_SIZE))
    ap.add_argument("--width", type=int, default=0)
    ap.add_argument("--height", type=int, default=0)
    ap.add_argument("--particles", type=int, default=1600)
    ap.add_argument("--particle-life", type=int, default=220)
    ap.add_argument("--seconds", type=float, default=10.0)
    ap.add_argument("--fps", type=int, default=24)
    ap.add_argument("--max-iter", type=int, default=90)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    width, height = _ASPECT_SIZE[args.aspect]
    if args.width:
        width = args.width
    if args.height:
        height = args.height

    spec = parse_spec(
        {
            "algorithm": args.algorithm,
            "seed": args.seed,
            "palette": args.palette,
            "width": width,
            "height": height,
            "particle_count": args.particles,
            "particle_life": args.particle_life,
            "max_iter": args.max_iter,
        }
    )
    out = Path(args.out)
    if args.mode == "still":
        img, stats = render_still(spec)
        out.parent.mkdir(parents=True, exist_ok=True)
        img.save(out)
        result = {"png": str(out), **stats}
    else:
        stats = render_video(spec, out, seconds=args.seconds, fps=args.fps)
        result = {"mp4": str(out), **stats}
    result["sha256"] = hashlib.sha256(out.read_bytes()).hexdigest()
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
