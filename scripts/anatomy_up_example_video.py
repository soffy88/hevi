#!/usr/bin/env python
"""Record an Anatomy example with the vendored ``drive.mjs`` and encode ≥10 s.

``scripts/drive.mjs`` turns a 3D figure to an exact angle and shoots the card,
so a video is a list of ``["turn", angle]`` + ``["shot", frame]`` actions and a
local ``ffmpeg`` call.  This script does exactly that for the vendored
``examples/turning-dial`` (the upstream 3D reference scene): one turn per frame
across a full sweep, 12 fps, 132 frames = 11.0 s.

Usage
-----
    python scripts/anatomy_up_example_video.py                 # 11 s sweep
    python scripts/anatomy_up_example_video.py --fps 30 --frames 330
    python scripts/anatomy_up_example_video.py --example dial-indicator --mode hover

Checks it makes (all real, nothing mocked):
    * every frame file exists and is a PNG at least 40×40 with ink;
    * consecutive frames differ (the figure actually moves);
    * the encoded mp4 is at least ``--seconds`` long (``ffprobe``).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hevi.capabilities.anatomy_explainer import verify  # noqa: E402
from hevi.capabilities.anatomy_explainer.renderer import encode_mp4, ffprobe_bin  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
ANATOMY = REPO / "third_party" / "anatomy"
OUT = REPO / "output" / "anatomy_up"
FINAL = REPO / "audit" / "anatomy_up"

#: name -> (page, wait ms before the first frame, action builder)
EXAMPLES: dict[str, dict[str, object]] = {
    "turning-dial": {"page": Path("examples/turning-dial/turning-dial-light.html")},
    "dial-indicator": {"page": Path("examples/dial-indicator/dial-indicator-light.html")},
}


class VideoError(RuntimeError):
    """The recorded video did not meet the brief."""


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def actions_for(name: str, frames_dir: Path, count: int, *, sweep: float) -> list[list[object]]:
    """drive.mjs action list: turn the figure one step, shoot one frame."""
    actions: list[list[object]] = [["wait", 400]]
    for index in range(count):
        if name == "turning-dial":
            actions.append(["turn", round((index * sweep) / max(1, count - 1), 3)])
        else:
            # A 2D figure has no turn controller: hold the carriage over the
            # third stop and let the page's own tour run between frames.
            actions.append(["move", None, 0.55, 0.45, 6])
        actions.append(["shot", str(frames_dir / f"{index:04d}.png")])
    return actions


def frames_stats(frames: list[Path]) -> dict[str, object]:
    from PIL import Image
    import numpy as np

    sizes = {Image.open(path).size for path in (frames[0], frames[len(frames) // 2], frames[-1])}
    arrays = [np.asarray(Image.open(path).convert("RGB"), dtype="int16") for path in frames]
    diffs = [float(np.abs(arrays[i] - arrays[i + 1]).mean()) for i in range(len(arrays) - 1)]
    changed = [float((np.abs(arrays[i] - arrays[i + 1]).max(2) > 8).mean()) for i in range(len(arrays) - 1)]
    if max(changed) < 0.002:
        raise VideoError("no frame differs from its neighbour by more than 0.2% of pixels: nothing moved")
    return {
        "frames": len(frames),
        "sizes": sorted(sizes),
        "mean_frame_diff": round(sum(diffs) / len(diffs), 4),
        "largest_frame_change": round(max(changed), 4),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--example", choices=sorted(EXAMPLES), default="turning-dial")
    parser.add_argument("--fps", type=int, default=12)
    parser.add_argument("--frames", type=int, default=132, help="132 frames at 12 fps = 11.0 s")
    parser.add_argument("--seconds", type=float, default=10.0, help="minimum duration the mp4 must reach")
    parser.add_argument("--width", type=int, default=1000)
    parser.add_argument("--height", type=int, default=820)
    parser.add_argument("--keep", action="store_true", help="keep the frame PNGs")
    args = parser.parse_args(argv)

    if args.frames < args.fps * args.seconds:
        parser.error(f"--frames {args.frames} at {args.fps} fps is under the required {args.seconds} s")

    spec = EXAMPLES[args.example]
    page = ANATOMY / str(spec["page"])
    if not page.is_file():
        raise VideoError(f"example page missing at {page}; build it with scripts/anatomy_up_examples.py")

    work = Path(tempfile.mkdtemp(prefix="anatomy-up-video-", dir=str(OUT if OUT.exists() else REPO)))
    frames_dir = work / "frames"
    frames_dir.mkdir(parents=True)
    try:
        actions = actions_for(args.example, frames_dir, args.frames, sweep=360.0)
        script_path = work / "actions.json"
        script_path.write_text(json.dumps(actions), encoding="utf-8")
        stdout = verify.run_script(
            "drive.mjs",
            [
                str(page),
                "--actions",
                str(script_path),
                "--width",
                str(args.width),
                "--height",
                str(args.height),
                "--scale",
                "1",
            ],
            label="Anatomy drive recording",
            timeout=3600,
            expect=("console:",),
        )
        verify.check_console(stdout, label="Anatomy drive recording")
        shots = sum(1 for row in stdout.splitlines() if row.startswith("shot "))
        frames = sorted(frames_dir.glob("*.png"))
        if len(frames) != args.frames:
            raise VideoError(f"drive.mjs shot {shots} frames, wrote {len(frames)} of {args.frames} {frames_dir}")
        stats = frames_stats(frames)
        stats["drive_shots"] = shots

        mp4 = work / f"{args.example}-drive.mp4"
        encode_mp4(frames_dir, mp4, fps=args.fps)
        probe = subprocess.run(
            [ffprobe_bin(), "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(mp4)],
            capture_output=True,
            text=True,
            check=True,
        )
        probe_data = json.loads(probe.stdout)
        stream = next(s for s in probe_data["streams"] if s["codec_type"] == "video")
        duration = float(probe_data["format"]["duration"])
        measured = {
            "duration_s": round(duration, 3),
            "width": stream["width"],
            "height": stream["height"],
            "codec": stream["codec_name"],
            "fps": stream["avg_frame_rate"],
            "nb_frames": int(stream.get("nb_frames", 0)),
            "size_bytes": mp4.stat().st_size,
            "sha256": sha256(mp4),
        }
        if duration + 1e-6 < args.seconds:
            raise VideoError(f"encoded mp4 is {duration:.3f}s, under the required {args.seconds}s")
        measured["min_duration_required"] = args.seconds

        # Keep the evidence: the mp4, one frame and the probe, next to the report.
        FINAL.mkdir(parents=True, exist_ok=True)
        keep = FINAL / "video"
        keep.mkdir(parents=True, exist_ok=True)
        shutil.copy2(mp4, keep / mp4.name)
        shutil.copy2(frames[0], keep / f"{args.example}-frame-0000.png")
        shutil.copy2(frames[len(frames) // 2], keep / f"{args.example}-frame-mid.png")
        (keep / f"{args.example}-ffprobe.json").write_text(
            json.dumps(probe_data, indent=2, sort_keys=True), encoding="utf-8"
        )
        summary = {
            "example": args.example,
            "page": str(page.relative_to(REPO)),
            "fps": args.fps,
            **stats,
            "video": measured,
            "artifacts": {
                "mp4": str((keep / mp4.name).relative_to(REPO)),
                "frames": str(frames_dir),
            },
        }
        (FINAL / "example_video.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(summary, indent=2, sort_keys=True))
        print(f"\nexample video passed: {duration:.3f}s, {measured['width']}x{measured['height']} {measured['codec']}")
        return 0
    except VideoError as error:
        print(f"example video failed: {error}", file=sys.stderr)
        return 1
    finally:
        if not args.keep:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
