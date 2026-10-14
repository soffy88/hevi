"""SCENE3D kids-content gate (KIDS_ANIME_DIRECTION.md).

The product direction (user 2026-10-14 20:06) is 2–6 year old viewers, so every
scene3d shot must clear a small set of hard gates before it is considered good:

* **No photosensitive flicker** — the mean frame brightness may not oscillate
  faster than 3 Hz (WCAG 2.3.1 / Harding).  Star twinkle is included because it
  modulates the average frame luminance.
* **Slow pacing** — a single shot must last at least 2.5 s; no fast cuts.
* **Bounded saturation** — the palette must stay bright and soft, not
  oversaturated.

The gate is deliberately small and pure: it takes decoded frames (PIL images or
file paths) and returns a structured report.  It never returns a fake pass —
an unreadable frame is an error.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = ["KidsGateReport", "evaluate_frames", "extract_frames", "MIN_SHOT_SECONDS"]

# Hard gates (see KIDS_ANIME_DIRECTION.md).
MIN_SHOT_SECONDS = 2.5
MAX_FLICKER_HZ = 3.0
MAX_MEAN_SATURATION = 0.85
# A tiny bit of headroom so 30 fps sampling noise does not trip the gate.
_FLICKER_TOLERANCE_HZ = 0.5


@dataclass
class KidsGateReport:
    """Outcome of the kids gate over a decoded shot."""

    passed: bool
    duration_s: float
    fps: float
    mean_luma: float = 0.0
    mean_saturation: float = 0.0
    flicker_hz: float = 0.0
    flicker_amplitude: float = 0.0
    failures: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "duration_s": self.duration_s,
            "fps": self.fps,
            "mean_luma": self.mean_luma,
            "mean_saturation": self.mean_saturation,
            "flicker_hz": self.flicker_hz,
            "flicker_amplitude": self.flicker_amplitude,
            "failures": list(self.failures),
        }


def _load_frames(frames: list[Any]) -> list[Any]:
    """Normalise a mix of PIL images / paths into a list of RGB numpy arrays."""
    import numpy as np
    from PIL import Image

    out = []
    for fr in frames:
        img = fr if hasattr(fr, "convert") else Image.open(fr)
        arr = np.asarray(img.convert("RGB"), dtype=np.float32) / 255.0
        out.append(arr)
    if not out:
        raise ValueError("kids gate: no frames supplied")
    return out


def _mean_luma_and_saturation(arr: Any) -> tuple[float, float]:
    import numpy as np

    r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]
    luma = 0.2126 * r + 0.7152 * g + 0.0722 * b
    mx = np.max(arr, axis=-1)
    mn = np.min(arr, axis=-1)
    sat = np.where(mx > 1e-6, (mx - mn) / np.maximum(mx, 1e-6), 0.0)
    return float(luma.mean()), float(sat.mean())


def _dominant_flicker_hz(series: list[float], fps: float) -> tuple[float, float]:
    """Return (peak frequency Hz, normalised amplitude) of a 1-D brightness signal.

    Uses a real FFT; the DC term is removed first so a constant brightness has
    no peak.  Amplitude is the peak magnitude divided by the signal length, so
    a full-swing flicker approaches ~1.0.
    """
    import numpy as np

    x = np.asarray(series, dtype=np.float64)
    x = x - x.mean()
    n = len(x)
    if n < 4 or np.allclose(x, 0.0):
        return 0.0, 0.0
    spectrum = np.abs(np.fft.rfft(x)) / n
    freqs = np.fft.rfftfreq(n, d=1.0 / fps)
    # ignore DC (index 0).
    spectrum[0] = 0.0
    k = int(np.argmax(spectrum))
    return float(freqs[k]), float(spectrum[k])


def evaluate_frames(
    frames: list[Any],
    *,
    fps: float,
    duration_s: float | None = None,
) -> KidsGateReport:
    """Run the kids gate over an ordered list of frames.

    ``frames`` may be PIL images or paths.  ``fps`` is the sampling rate of the
    list (usually the shot fps).  ``duration_s`` defaults to ``len/fps``.
    """
    arrays = _load_frames(frames)
    n = len(arrays)
    if duration_s is None:
        duration_s = n / fps if fps > 0 else 0.0

    lumas: list[float] = []
    sats: list[float] = []
    for arr in arrays:
        lum, sat = _mean_luma_and_saturation(arr)
        lumas.append(lum)
        sats.append(sat)

    mean_luma = sum(lumas) / n
    mean_sat = sum(sats) / n
    flicker_hz, flicker_amp = _dominant_flicker_hz(lumas, fps)

    failures: list[str] = []
    if duration_s < MIN_SHOT_SECONDS:
        failures.append(
            f"shot too short: {duration_s:.2f}s < {MIN_SHOT_SECONDS}s (no fast cuts)"
        )
    if flicker_hz > MAX_FLICKER_HZ + _FLICKER_TOLERANCE_HZ and flicker_amp > 0.01:
        failures.append(
            f"brightness flicker {flicker_hz:.2f}Hz exceeds {MAX_FLICKER_HZ}Hz cap"
        )
    if mean_sat > MAX_MEAN_SATURATION:
        failures.append(
            f"mean saturation {mean_sat:.3f} exceeds {MAX_MEAN_SATURATION} cap"
        )

    return KidsGateReport(
        passed=not failures,
        duration_s=float(duration_s),
        fps=float(fps),
        mean_luma=mean_luma,
        mean_saturation=mean_sat,
        flicker_hz=flicker_hz,
        flicker_amplitude=flicker_amp,
        failures=failures,
    )


def extract_frames(video: str | Path, *, fps: float, count: int, out_dir: str | Path) -> list[Path]:
    """Decode ``count`` frames from ``video`` at ``fps`` into ``out_dir``.

    Thin ffmpeg wrapper; used by the e2e runner so the kids gate can run on a
    finished mp4 without re-rendering.
    """
    import subprocess

    from hevi.layer4_legacy.scene3d.renderer import FFMPEG

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    pattern = out_dir / "kf_%05d.png"
    cmd = [
        FFMPEG, "-y",
        "-i", str(video),
        "-vf", f"fps={fps}",
        "-frames:v", str(count),
        str(pattern),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return sorted(out_dir.glob("kf_*.png"))


def _hz_to_period(hz: float) -> float:
    return math.inf if hz <= 0 else 1.0 / hz
