"""Deterministic beat-click audio generation test (H5).

The kinetic specs reference a git-ignored WAV. The renderer must be able to
regenerate it locally with ffmpeg lavfi; the synthesis has to be byte-identical
across runs so that renders stay reproducible.
"""

import subprocess
import tempfile
from pathlib import Path

from hevi.motion_templates.render import compute_file_sha256, generate_beat_click_track


def _probe_duration(path: Path) -> float:
    res = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True,
    )
    return float(res.stdout.strip())


def test_beat_click_track_is_deterministic_and_valid():
    with tempfile.TemporaryDirectory() as tmp:
        a = Path(tmp) / "a.wav"
        b = Path(tmp) / "b.wav"
        generate_beat_click_track(120.0, 10.0, a)
        generate_beat_click_track(120.0, 10.0, b)

        assert a.is_file() and b.is_file()
        assert compute_file_sha256(a) == compute_file_sha256(b), "click synthesis must be deterministic"
        assert abs(_probe_duration(a) - 10.0) < 0.05
