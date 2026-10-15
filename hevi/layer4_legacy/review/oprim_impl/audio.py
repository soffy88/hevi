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


def spectral_flatness(
    *,
    path: str | Path,
    fft_size: int = 4096,
    energy_floor_db: float = -60.0,
) -> float | None:
    """Spectral flatness (0..1) of the full file via sliding FFT windows.

    Computes geometric_mean / arithmetic_mean of the FFT power spectrum —
    the standard spectral flatness measure.  White noise has a flat
    spectrum (flatness near 0.5+); tones and speech have highly peaked
    spectra (flatness near 0).

    The whole file is split into windows; silent/low-energy windows
    are dropped (they have zero power and would bias flatness to 1.0),
    then the median flatness across windows is returned.  A film whose
    opening is digital silence (but whose body is real audio) is
    therefore not flagged as white noise.  Returns None when not
    measurable.
    """
    import numpy as np

    dest = Path(path)
    info = probe_media(dest)
    if not info.has_audio or info.duration_s <= 0:
        return None
    # Extract PCM samples as float32 mono via ffmpeg.
    proc = subprocess.run(
        [
            FFMPEG,
            "-nostats",
            "-hide_banner",
            "-i",
            str(dest),
            "-f",
            "f32le",
            "-acodec",
            "pcm_f32le",
            "-ac",
            "1",
            "-",
        ],
        capture_output=True,
        text=False,
        timeout=1800,
        check=False,
    )
    if proc.returncode != 0:
        return None
    raw = proc.stdout
    if not raw:
        return None
    samples = np.frombuffer(raw, dtype=np.float32)
    if len(samples) < fft_size:
        return None

    step = fft_size // 2
    energy_floor = 10.0 ** (energy_floor_db / 10.0)
    flatness_values: list[float] = []
    for start in range(0, len(samples) - fft_size + 1, step):
        window = np.hanning(fft_size)
        seg = samples[start : start + fft_size]
        power = np.abs(np.fft.rfft(seg * window)) ** 2
        if float(power.mean()) < energy_floor:
            continue  # silent/low-energy window: not evidence of white noise
        power = power + 1e-20  # epsilon to avoid log(0)
        geomean = float(np.exp(np.mean(np.log(power))))
        arithmean = float(np.mean(power))
        flatness_values.append(geomean / arithmean)
    if not flatness_values:
        # Everything silent — report the single full-file flatness so
        # the caller can still distinguish "truly silent" (≈1.0) from
        # "broadband white noise" (≈0.5) by combining with silence_ratio.
        seg = samples[:fft_size]
        power = np.abs(np.fft.rfft(seg * np.hanning(fft_size))) ** 2 + 1e-20
        geomean = float(np.exp(np.mean(np.log(power))))
        arithmean = float(np.mean(power))
        return round(geomean / arithmean, 4)
    return round(float(np.median(flatness_values)), 4)


def clipped_sample_ratio(
    *,
    path: str | Path,
    threshold: float = 0.999,
) -> float | None:
    """Fraction of PCM samples whose absolute value >= ``threshold`` (clipping).

    Returns a ratio in [0, 1]; None when the file has no audio stream.
    """
    import numpy as np

    dest = Path(path)
    info = probe_media(dest)
    if not info.has_audio:
        return None
    proc = subprocess.run(
        [
            FFMPEG,
            "-nostats",
            "-hide_banner",
            "-i",
            str(dest),
            "-f",
            "f32le",
            "-acodec",
            "pcm_f32le",
            "-ac",
            "1",
            "-",
        ],
        capture_output=True,
        text=False,
        timeout=1800,
        check=False,
    )
    if proc.returncode != 0:
        return None
    raw = proc.stdout
    if not raw:
        return None
    samples = np.frombuffer(raw, dtype=np.float32)
    if len(samples) == 0:
        return None
    count = int(np.sum(np.abs(samples) >= threshold))
    return round(count / len(samples), 6)


def longest_clipped_run_s(
    *,
    path: str | Path,
    threshold: float = 0.999,
    sample_rate: int = 44100,
) -> float | None:
    """Longest continuous run of clipped samples, in seconds.

    A brief peak that grazes full scale (a loud transient) clips only a
    handful of samples; a real overdriven/limiter-pumping passage clips
    thousands in a row.  Measuring the *continuous run* separates the two far
    better than a raw ratio (which a long clip with sparse peaks can inflate).
    Returns None when the file has no audio stream.
    """
    import numpy as np

    dest = Path(path)
    info = probe_media(dest)
    if not info.has_audio:
        return None
    proc = subprocess.run(
        [
            FFMPEG,
            "-nostats",
            "-hide_banner",
            "-i",
            str(dest),
            "-f",
            "f32le",
            "-acodec",
            "pcm_f32le",
            "-ac",
            "1",
            "-ar",
            str(int(sample_rate)),
            "-",
        ],
        capture_output=True,
        text=False,
        timeout=1800,
        check=False,
    )
    if proc.returncode != 0 or not proc.stdout:
        return None
    samples = np.frombuffer(proc.stdout, dtype=np.float32)
    if samples.size == 0:
        return None
    clipped = np.abs(samples) >= threshold
    if not clipped.any():
        return 0.0
    # Longest run of consecutive True via run-length on the index gaps.
    idx = np.flatnonzero(clipped)
    # boundaries where the clipped index jumps by more than 1
    breaks = np.flatnonzero(np.diff(idx) > 1)
    starts = np.concatenate(([0], breaks + 1))
    ends = np.concatenate((breaks, [idx.size - 1]))
    longest = int((idx[ends] - idx[starts] + 1).max())
    return round(longest / float(sample_rate), 4)


def transient_click_count(
    *,
    path: str | Path,
    jump_threshold: float = 0.5,
) -> int | None:
    """Count 10-ms windows with an abrup sample-to-sample jump exceeding ``jump_threshold``.

    Each such window is counted as one transient click/popup event.  Returns None
    when the file has no audio stream.  A high count indicates rapid amplitude
    discontinuities typical of digital clicks or pop artifacts.
    """
    import numpy as np

    dest = Path(path)
    info = probe_media(dest)
    if not info.has_audio:
        return None
    proc = subprocess.run(
        [
            FFMPEG,
            "-nostats",
            "-hide_banner",
            "-i",
            str(dest),
            "-f",
            "f32le",
            "-acodec",
            "pcm_f32le",
            "-ac",
            "1",
            "-",
        ],
        capture_output=True,
        text=False,
        timeout=1800,
        check=False,
    )
    if proc.returncode != 0:
        return None
    raw = proc.stdout
    if not raw:
        return None
    samples = np.frombuffer(raw, dtype=np.float32)
    if len(samples) < 2:
        return 0
    diffs = np.abs(np.diff(samples))
    return int(np.sum(diffs > jump_threshold))


__all__ = [
    "audio_duration_s",
    "loudness_lufs",
    "silence_ratio",
    "spectral_flatness",
    "silence_windows",
    "clipped_sample_ratio",
    "longest_clipped_run_s",
    "transient_click_count",
]
