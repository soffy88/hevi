"""Command line interface for Hevi Motion Templates renderer."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hevi.motion_templates.render import render


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="hevi.motion_templates.cli",
        description="Render deterministic Canvas draw(t) motion templates to MP4.",
    )
    parser.add_argument(
        "--template",
        required=True,
        help="Template name (morph_ui, timeline_explainer, kinetic_lyrics, layer_build) or HTML path.",
    )
    parser.add_argument(
        "--spec",
        required=True,
        help="Path to JSON spec file.",
    )
    parser.add_argument(
        "--out",
        required=True,
        help="Output directory or MP4 file path.",
    )
    parser.add_argument(
        "--aspect",
        choices=["9:16", "16:9", "1:1"],
        default="9:16",
        help="Target aspect ratio (default: 9:16).",
    )
    parser.add_argument(
        "--fps",
        type=int,
        default=30,
        help="Render framerate (default: 30).",
    )
    parser.add_argument(
        "--audio",
        default=None,
        help="Optional audio/music track to mix into output video.",
    )
    parser.add_argument(
        "--no-contact-sheet",
        action="store_true",
        help="Skip generating 3x3 contact sheet PNG.",
    )

    args = parser.parse_args()

    out_path = Path(args.out)
    if out_path.is_dir() or str(args.out).endswith("/") or not out_path.suffix:
        out_path.mkdir(parents=True, exist_ok=True)
        spec_stem = Path(args.spec).stem
        safe_aspect = args.aspect.replace(":", "_")
        target_mp4 = out_path / f"{spec_stem}_{safe_aspect}.mp4"
    else:
        target_mp4 = out_path

    print(f"[AMTPL] Rendering template='{args.template}', aspect='{args.aspect}', spec='{args.spec}'...")
    result = render(
        template=args.template,
        spec=args.spec,
        out_mp4=target_mp4,
        fps=args.fps,
        aspect=args.aspect,
        contact_sheet=not args.no_contact_sheet,
        audio_path=args.audio,
    )

    print(f"[AMTPL] Success:")
    print(f"  MP4:           {result.mp4_path}")
    print(f"  Resolution:    {result.width}x{result.height} @ {result.fps}fps")
    print(f"  Duration:      {result.duration:.2f}s ({result.frames_count} frames)")
    print(f"  MP4 SHA256:    {result.sha256}")
    if result.contact_sheet_path:
        print(f"  Contact Sheet: {result.contact_sheet_path}")
        print(f"  Contact SHA:   {result.contact_sha256}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
