"""Audio measurement for the review gate: presence, loudness, silence (oprim).

Loudness uses ffmpeg's ``ebur128`` (deterministic, no ML).  Silence uses
``silencedetect``.  Both return ``None`` when the measurement could not be made
— ``None`` means "not measured" and is never conflated with a numeric 0.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from hevi.layer4_legacy.review.oprim_impl.media import FFMPEG, FFPROBE, probe_media

_LUFS_RE = re.compile(r"Integrated loudness:\s*\n\s*I:\s*(-?[\d.]+)\s*LUFS", re.IGNORECASE)
_SILENCE_START_RE = re.compile(r"silence_start:\s*(-?[\d.]+)")
_SILENCE_END_RE = re.compile(r"silence_end:\s*(-?[\d.]+)")


def loudness_lufs(*, path: str | Path) -> float | None:
    """Integrated loudness (LUFS) via ffmpeg ebur128. None = not measurable."""
    dest = Path(path)
    if not probe_media(dest).has_audio:
        return None
    proc = subprocess.run(
        [
            FFMPEG,
            "-nostats",
            "-hide_banner",
            "-i",
            str(dest),
            "-af",
            "ebur128=peak=none",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        timeout=1800,
        check=False,
    )
    m = _LUFS_RE.search(proc.stderr or "")
    return float(m.group(1)) if m else None


def silence_windows(
    *,
    path: str | Path,
    noise_db: float = -45.0,
    min_duration_s: float = 0.5,
) -> list[tuple[float, float]]:
    """Real silence intervals from ffmpeg silencedetect: [(start_s, end_s), ...]."""
    dest = Path(path)
    if not probe_media(dest).has_audio:
        return []
    proc = subprocess.run(
        [
            FFMPEG,
            "-nostats",
            "-hide_banner",
            "-i",
            str(dest),
            "-af",
            f"silencedetect=noise={noise_db}dB:d={min_duration_s}",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        timeout=1800,
        check=False,
    )
    text = proc.stderr or ""
    starts = [float(x) for x in _SILENCE_START_RE.findall(text)]
    ends = [float(x) for x in _SILENCE_END_RE.findall(text)]
    out: list[tuple[float, float]] = []
    for i, start in enumerate(starts):
        end = ends[i] if i < len(ends) else start
        out.append((round(start, 3), round(end, 3)))
    return out


def silence_ratio(
    *,
    path: str | Path,
    noise_db: float = -45.0,
    min_duration_s: float = 0.5,
) -> float | None:
    """Fraction of the runtime that is silence. None when there is no audio."""
    dest = Path(path)
    info = probe_media(dest)
    if not info.has_audio or info.duration_s <= 0:
        return None
    windows = silence_windows(path=dest, noise_db=noise_db, min_duration_s=min_duration_s)
    total = sum(max(0.0, e - s) for s, e in windows)
    return round(min(1.0, total / info.duration_s), 4)


def audio_duration_s(*, path: str | Path) -> float | None:
    """Duration of the audio stream; None when there is no audio stream."""
    dest = Path(path)
    proc = subprocess.run(
        [
            FFPROBE,
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(dest),
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    raw = (proc.stdout or "").strip().splitlines()
    if not raw:
        return None
    try:
        return round(float(raw[0]), 3)
    except ValueError:
        return None


__all__ = ["audio_duration_s", "loudness_lufs", "silence_ratio", "silence_windows"]
