#!/usr/bin/env python
"""Generate deterministic beat-click audio tracks for Hevi motion templates.

Kinetic specs reference WAV files under ``assets/audio/`` which are git-ignored
(``*.wav``), so a fresh clone cannot reproduce the render unless the audio can be
regenerated. This script synthesises the click track locally with ffmpeg's
``aevalsrc`` lavfi source; the renderer also calls the same helper automatically
when a spec's ``audio`` path is missing.

Usage::

    PYTHONPATH=$PWD .venv/bin/python scripts/gen_motion_template_audio.py
    PYTHONPATH=$PWD .venv/bin/python scripts/gen_motion_template_audio.py --bpm 120 --duration 10 --out assets/audio/beat_120bpm_click.wav

No paid API, no network: pure local ffmpeg synthesis.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hevi.motion_templates.render import generate_beat_click_track

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = REPO_ROOT / "assets" / "audio" / "beat_120bpm_click.wav"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a deterministic beat-click WAV via ffmpeg lavfi.")
    parser.add_argument("--bpm", type=float, default=120.0, help="Beats per minute (default: 120).")
    parser.add_argument("--duration", type=float, default=10.0, help="Duration in seconds (default: 10).")
    parser.add_argument("--freq", type=float, default=1200.0, help="Click tone frequency in Hz (default: 1200).")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help=f"Output WAV path (default: {DEFAULT_OUT}).")
    args = parser.parse_args()

    out = Path(args.out)
    if not out.is_absolute():
        out = (REPO_ROOT / out).resolve()
    generate_beat_click_track(args.bpm, args.duration, out, freq=args.freq)
    print(f"[AMTPL] Wrote {out} ({out.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
