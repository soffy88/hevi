"""Pure audio maths for zero-cost lines: procedural (own, licence-free) BGM,
RMS envelope -> quantised mouth visemes.  numpy only, no IO."""

from __future__ import annotations

import numpy as np

_PROGRESSIONS: dict[str, list[tuple[float, float, float]]] = {
    "warm": [(220, 277.2, 329.6), (196, 246.9, 293.7), (174.6, 220, 261.6), (196, 246.9, 329.6)],
    "tense": [(110, 130.8, 164.8), (103.8, 130.8, 155.6), (98, 123.5, 146.8), (103.8, 123.5, 155.6)],
    "bright": [(261.6, 329.6, 392), (293.7, 349.2, 440), (220, 261.6, 329.6), (246.9, 311.1, 392)],
}
MOODS = tuple(_PROGRESSIONS)


def synth_bgm(seconds: float, *, mood: str = "warm", sr: int = 44100, seed: int = 7) -> np.ndarray:
    """Chord-progression pad (+ soft pulse for ``bright``) -> int16 stereo (N, 2)."""
    if mood not in _PROGRESSIONS:
        raise ValueError(f"unknown mood {mood!r}; expected {MOODS}")
    if seconds <= 0:
        raise ValueError("seconds must be positive")
    rng = np.random.default_rng(seed)
    t = np.arange(int(seconds * sr)) / sr
    prog = _PROGRESSIONS[mood]
    seg = 4.0
    y = np.zeros_like(t)
    for k, chord in enumerate(prog * int(seconds // (seg * 4) + 1)):
        a, b = k * seg, (k + 1) * seg + 1.0
        m = (t >= a) & (t < b)
        if not m.any():
            continue
        tt = t[m] - a
        env = np.minimum(1, tt / 1.2) * np.minimum(1, np.maximum(0, (b - a - tt) / 1.2))
        for f in chord:
            y[m] += env * (np.sin(2 * np.pi * f * tt) * 0.5 + np.sin(2 * np.pi * f * 2.003 * tt) * 0.12)
    if mood == "bright":
        beat = (np.sin(2 * np.pi * 2 * t) > 0.97).astype(float)
        y += np.convolve(beat, np.exp(-np.arange(2000) / 300), "same") * rng.normal(0, 0.3, len(t))
    y += rng.normal(0, 0.004, len(t))
    y = y / (np.abs(y).max() + 1e-9) * 0.5
    fade = np.minimum(1, np.minimum(t / 2, (seconds - t) / 2))
    mono = (y * fade * 32767).astype(np.int16)
    return np.stack([mono, mono], 1)


def rms_from_pcm(pcm: np.ndarray, *, fps: int, sr: int = 16000) -> np.ndarray:
    """Mono float PCM -> per-video-frame RMS normalised to the 95th percentile."""
    if fps <= 0:
        raise ValueError("fps must be positive")
    hop = sr // fps
    n = len(pcm) // hop
    if n == 0:
        return np.zeros(0, np.float32)
    e = np.sqrt((pcm[: n * hop].reshape(n, hop) ** 2).mean(1))
    return e / (np.percentile(e, 95) + 1e-6)


def mouth_series(env: np.ndarray) -> np.ndarray:
    """Smooth RMS into a 0..1 mouth-open series with 5 quantised visemes."""
    if len(env) == 0:
        return env
    e = np.convolve(env, np.ones(2) / 2, "same")
    e = np.clip((e - 0.08) / 0.8, 0, 1)
    return np.round(e * 4) / 4


__all__ = ["MOODS", "mouth_series", "rms_from_pcm", "synth_bgm"]
