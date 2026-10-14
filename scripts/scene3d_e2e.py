#!/usr/bin/env python3
"""Render the three SCENE3D production shots sequentially in one process.

Used by SCENE3D_E2E.sh; also runnable directly::

    python scripts/scene3d_e2e.py [--out output/scene3d_e2e] [--fps 30]

This:
  1. Renders little_planet_orbit (16:9, 12 s, 1080p)
  2. Renders fox_in_wheat     (9:16, 12 s, 1080p)
  3. Renders through_star_sea (9:16, 13 s, 1080p)
  4. Collects per-shot metrics (ffprobe + sha256) and writes a roll-up JSON
     and contact sheets.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hevi.layer4_legacy.scene3d import renderer as R  # noqa: E402


SHOTS = [
    ("little_planet_orbit", 30, 12.0),
    ("fox_in_wheat", 30, 12.0),
    ("through_star_sea", 30, 13.0),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="output/scene3d_e2e")
    ap.add_argument("--resolution", type=int, default=1080)
    args = ap.parse_args()

    out_root = Path(args.out)
    out_root.mkdir(parents=True, exist_ok=True)
    rollup: dict[str, dict] = {}
    t0 = time.perf_counter()

    for name, fps, duration in SHOTS:
        src = ROOT / "hevi/layer4_legacy/scene3d" / "examples" / f"{name}.json"
        spec = json.loads(src.read_text(encoding="utf-8"))
        spec["fps"] = fps
        spec["duration_s"] = duration
        spec["resolution"] = args.resolution

        out = out_root / name
        out.mkdir(parents=True, exist_ok=True)
        (out / "scene.json").write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")

        from hevi.layer4_legacy.scene3d.schema import parse_scene
        from hevi.layer4_legacy.scene3d.renderer import SceneRenderer

        scene = parse_scene(spec)
        r = SceneRenderer(scene, out)
        m = r.render()
        m["sha256"] = R.sha256(r.video_path)
        m["probe"] = R.ffprobe(r.video_path)

        # contact sheet
        frames = sorted(r.frames_dir.glob("frame_*.png"))
        step = max(1, len(frames) // 25)
        sample = frames[::step] or frames
        sheet = R.make_contact_sheet(sample, out / f"{name}_contact_sheet.png")
        m["contact_sheet"] = str(sheet)
        (out / "metrics.json").write_text(
            json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        rollup[name] = m
        print(f"[ok] {name}: {m['frame_count']} frames in {m['total_render_s']}s ({m['per_frame_s']}s/frame)")

    total = time.perf_counter() - t0
    summary = {
        "total_render_s": round(total, 3),
        "fps": 30,
        "resolution": args.resolution,
        "shots": rollup,
    }
    (out_root / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
