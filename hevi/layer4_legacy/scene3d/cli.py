"""SCENE3D command-line interface.

Usage:
    python -m hevi.layer4_legacy.scene3d.cli render <scene.json> --out <dir> [--no-encode]
    python -m hevi.layer4_legacy.scene3d.cli scenes   # list bundled example scenes
    python -m hevi.layer4_legacy.scene3d.cli validate <scene.json>

The renderer is deterministic on CPU (SwiftShader) and produces one PNG per
frame plus an h264 MP4 at 30 fps, a contact sheet, and a metrics JSON.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import renderer as R
from .schema import load_scene, validate_scene


def _example_dir() -> Path:
    return Path(__file__).resolve().parent / "examples"


def cmd_render(args: argparse.Namespace) -> int:
    spec = load_scene(args.scene)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    # Persist a resolved copy of the scene for reproducibility.
    (out / "scene.json").write_text(
        json.dumps(_spec_to_dict(spec), ensure_ascii=False, indent=2), encoding="utf-8"
    )

    r = R.SceneRenderer(spec, out)
    metrics = r.render()
    metrics["sha256"] = R.sha256(r.video_path)
    metrics["probe"] = R.ffprobe(r.video_path)

    # Contact sheet (sample ~25 frames).
    frames = sorted(r.frames_dir.glob("frame_*.png"))
    step = max(1, len(frames) // 25)
    sample = frames[::step]
    if sample:
        sheet = R.make_contact_sheet(sample, out / f"{spec.name}_contact_sheet.png")
        metrics["contact_sheet"] = str(sheet)

    (out / "metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    return 0


def _spec_to_dict(spec):  # local import to avoid circulars
    from .schema import scene_to_dict

    return scene_to_dict(spec)


def cmd_validate(args: argparse.Namespace) -> int:
    spec = load_scene(args.scene)
    validate_scene(spec)
    print(f"OK: {args.scene} -> {spec.width}x{spec.height}, {spec.frame_count} frames")
    return 0


def cmd_scenes(args: argparse.Namespace) -> int:
    for p in sorted(_example_dir().glob("*.json")):
        spec = load_scene(p)
        print(f"{p.name}\t{spec.name}\t{spec.camera.aspect}\t{spec.duration_s}s")
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="scene3d", description="Hevi CPU 3D scene renderer")
    sub = ap.add_subparsers(dest="cmd", required=True)

    rp = sub.add_parser("render", help="render a scene to video")
    rp.add_argument("scene", help="path to scene JSON")
    rp.add_argument("--out", required=True, help="output directory")
    rp.set_defaults(func=cmd_render)

    vp = sub.add_parser("validate", help="validate a scene JSON")
    vp.add_argument("scene", help="path to scene JSON")
    vp.set_defaults(func=cmd_validate)

    sp = sub.add_parser("scenes", help="list bundled example scenes")
    sp.set_defaults(func=cmd_scenes)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
