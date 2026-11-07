"""Gate-side spectral hygiene analysis (infrasound + HF narrowband spike).

Why this lives in the gate layer and not in earshot: ``audio.earshot_gate``
consumes earshot's model-free ``measure`` for loudness / true peak /
clipping, but earshot's own band spectrum starts at 20 Hz and only reports
whole-band shares near 16 kHz — it has no infrasound metric and cannot
localise a narrowband whine.  Both failure modes below are known artefacts
of *generated* audio (heavy subsonic rumble that makes speakers buzz; a
fixed ~16 kHz synthesis whine), so the gate computes them itself, straight
from the decoded PCM: numpy/scipy STFT, soundfile decode (ffmpeg pipe as
fallback for containers soundfile cannot open).  No model, no network, no
new dependency.  Definitions and threshold rationale: docs/rules/audio_gate.md.

Metrics (from the time-averaged power spectrum of a Hann STFT; window is
~1 s at the file's sample rate, so frequency resolution is ~1 Hz and the
sub-20 Hz band is genuinely resolved, not one smeared bin):

``infrasound_ratio``
    Energy below 20 Hz (DC excluded) divided by total energy.  Clean
    speech/music measures in the 1e-5..1e-3 range here; the gate default
    ceiling is 0.01 (1 %, -20 dB).

``hf_spike_prominence_db``
    In the 15-17 kHz band, the strongest bin's level above the *local
    median* level (median over ±300 Hz around the bin, ±40 Hz guard
    excluded), in dB.  A pure tone stands tens of dB over its
    neighbourhood; broadband HF content (cymbals, "air") lifts the local
    median too, so it does not read as a spike.  Not assessable when
    Nyquist <= 17 kHz — such a file physically cannot carry the artefact.

    Prominence alone is meaningless on a numerically silent band (a pure
    sine fixture leaves only arithmetic noise up there, whose max-bin
    statistic is unstable), so the verdict also requires significance:
    the peak bin must carry at least ``HF_MIN_PEAK_SHARE`` (1e-6, -60 dB)
    of the file's total spectral energy.  An injected 16 kHz tone at
    amplitude 0.02 over real narration carries ~1e-2; arithmetic-noise
    bins carry ~1e-14 or less.
"""

from __future__ import annotations

import io
import shutil
import subprocess
from pathlib import Path
from typing import Any

import numpy as np

# Band edges / neighbourhood geometry (see module docstring).
INFRASOUND_CEILING_HZ = 20.0
HF_BAND_HZ = (15_000.0, 17_000.0)
HF_NEIGHBORHOOD_HZ = 300.0
HF_GUARD_HZ = 40.0
HF_MIN_PEAK_SHARE = 1e-6  # peak bin's min share of total energy to matter

_MIN_SAMPLES = 512  # below this a ~1 Hz-resolved spectrum is meaningless


class SpectralError(RuntimeError):
    """Audio could not be decoded or is too short to analyse."""


def _ffmpeg_bin() -> str | None:
    found = shutil.which("ffmpeg")
    if found:
        return found
    local = Path.home() / ".local" / "bin" / "ffmpeg"
    return str(local) if local.is_file() else None


def _load_mono(media_path: Path) -> tuple[np.ndarray, int]:
    """Decode ``media_path`` to mono float samples + sample rate.

    soundfile first (wav/flac/ogg/opus/mp3 on modern libsndfile); on any
    failure, decode through ffmpeg's stdout pipe (handles mp4/m4a/...).
    """
    import soundfile as sf

    path = Path(media_path)
    try:
        data, sr = sf.read(str(path), always_2d=True, dtype="float32")
    except Exception:
        data = None
    if data is None:
        ffmpeg = _ffmpeg_bin()
        if ffmpeg is None:
            raise SpectralError(
                f"cannot decode {path}: soundfile failed and no ffmpeg on PATH"
            )
        proc = subprocess.run(
            [ffmpeg, "-v", "error", "-y", "-i", str(path),
             "-vn", "-ac", "1", "-f", "wav", "-"],
            capture_output=True,
            timeout=600,
        )
        if proc.returncode != 0 or not proc.stdout:
            tail = (proc.stderr or b"").decode(errors="replace").strip().splitlines()
            raise SpectralError(
                f"cannot decode {path}: ffmpeg: {tail[-1] if tail else 'no output'}"
            )
        try:
            data, sr = sf.read(io.BytesIO(proc.stdout), always_2d=True, dtype="float32")
        except Exception as exc:
            raise SpectralError(f"cannot decode {path}: {exc}") from exc
    mono = data.mean(axis=1).astype(np.float64)
    return mono, int(sr)


def _mean_power_spectrum(samples: np.ndarray, sr: int) -> tuple[np.ndarray, np.ndarray]:
    """Time-averaged power spectrum (Hann STFT, ~1 s window, 50 % hop)."""
    from scipy.signal import stft

    n = int(samples.shape[0])
    nperseg = min(n, sr)
    freqs, _, zxx = stft(
        samples,
        fs=sr,
        window="hann",
        nperseg=nperseg,
        noverlap=nperseg // 2,
        detrend=False,
        boundary=None,
        padded=False,
    )
    power = np.mean(np.abs(zxx) ** 2, axis=1)
    return freqs, power


def infrasound_ratio(freqs: np.ndarray, power: np.ndarray) -> float | None:
    """Share of total energy below 20 Hz (DC excluded); None if silent."""
    audible = freqs > 0
    total = float(power[audible].sum())
    if total <= 0.0:
        return None
    infra = float(power[audible & (freqs < INFRASOUND_CEILING_HZ)].sum())
    return infra / total


def hf_spike(
    freqs: np.ndarray, power: np.ndarray
) -> tuple[float | None, float | None, float | None]:
    """(peak frequency Hz, prominence dB over local median, energy share).

    The share is the peak bin's fraction of total spectral energy
    (f > 0) — the significance measure described in the module docstring.
    All three are None when the band cannot be examined at all.
    """
    lo, hi = HF_BAND_HZ
    band_idx = np.where((freqs >= lo) & (freqs <= hi))[0]
    if band_idx.size == 0:
        return None, None, None
    total = float(power[freqs > 0].sum())
    power_db = 10.0 * np.log10(power + 1e-30)
    best_freq: float | None = None
    best_prom: float | None = None
    best_share: float | None = None
    for i in band_idx:
        dist = np.abs(freqs - freqs[i])
        neigh = (dist <= HF_NEIGHBORHOOD_HZ) & (dist > HF_GUARD_HZ)
        if not neigh.any():
            continue
        prom = float(power_db[i] - np.median(power_db[neigh]))
        if best_prom is None or prom > best_prom:
            best_prom = prom
            best_freq = float(freqs[i])
            best_share = (float(power[i]) / total) if total > 0.0 else None
    return best_freq, best_prom, best_share


def measure_spectrum(samples: np.ndarray, sr: int) -> dict[str, Any]:
    """Spectral hygiene metrics for decoded mono ``samples`` at ``sr`` Hz."""
    samples = np.asarray(samples, dtype=np.float64).ravel()
    if samples.shape[0] < _MIN_SAMPLES:
        raise SpectralError(
            f"too short to analyse: {samples.shape[0]} samples (< {_MIN_SAMPLES})"
        )
    centred = samples - samples.mean()
    freqs, power = _mean_power_spectrum(centred, sr)
    ratio = infrasound_ratio(freqs, power)
    assessable = (sr / 2.0) > HF_BAND_HZ[1]
    if assessable:
        peak_freq, prominence, peak_share = hf_spike(freqs, power)
    else:
        peak_freq, prominence, peak_share = None, None, None
    return {
        "sample_rate": int(sr),
        "duration_s": round(samples.shape[0] / float(sr), 3),
        "infrasound_ratio": ratio,
        "hf_assessable": bool(assessable),
        "hf_peak_freq_hz": peak_freq,
        "hf_spike_prominence_db": prominence,
        "hf_peak_energy_share": peak_share,
    }


def analyze(media_path: Path) -> dict[str, Any]:
    """Decode ``media_path`` and return :func:`measure_spectrum` metrics."""
    samples, sr = _load_mono(Path(media_path))
    return measure_spectrum(samples, sr)
