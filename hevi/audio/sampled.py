"""Deterministic sampled-instrument engine for ``audio.score_render``.

Real-instrument path behind :mod:`hevi.audio.score_render`: instead of the
numpy synth recipes, a note is played back from a bundled one-shot sample
of a real instrument — nearest recorded pitch, nearest velocity layer,
pitch-shifted by resampling to the target note (the fractional ``midi``
in the index is the *detected* pitch, so the shift also corrects the
sample's tuning, exactly like upstream mgaudio does).

Sample library (vendored, see ``sampled_data/ATTRIBUTION.md``):

* Code design + index format adapted from **mg-styles-15** by
  Vincentwei1021 (MIT License) — ``lib/audio/mgaudio/samples.py``:
  nearest-pitch / nearest-velocity-layer picking, ``_VEL`` name-velocity
  table, stereo spaced-pair channel alignment before mono summing, and
  the velocity-relative gain rule.  A verbatim copy of that upstream
  file is kept in ``sampled_data/upstream/mgaudio_samples.py``.
* Audio content: a 102-file subset of **VCSL** (Versilian Studios
  Community Sample Library, CC0) as bundled by mg-styles-15 — pitched:
  piano / marimba / vibraphone / harp / glock(enspiel) / kalimba /
  wineglass; one-shot percussion: crash / timpani / woodblock /
  slapstick / suscymbal / cabasa / guiro / vibraslap.

Deliberate deviations from upstream mgaudio (determinism contract):

* Upstream ``Instrument.pick`` rotates round-robin variants through a
  mutable counter on an ``lru_cache``-d singleton, so the same score
  rendered twice in one process can pick different samples.
  ``score_render`` guarantees *same seed + same input -> identical
  bytes*; picking here is a pure function (nearest pitch, then nearest
  velocity layer, then file name) with no state.
* Pitch shifting is plain numpy linear-interpolation resampling — no
  numba (upstream ``_dsp.varispeed``) and no new dependencies;
  ``soundfile`` is already a hevi runtime dependency
  (``hevi/audio/effects.py`` etc.).
* Stereo samples are channel-aligned (spaced-pair comb-filter guard,
  after upstream ``_align_pair``) and summed to mono, because
  ``score_render`` mixes mono voices with its own panning.

Anything that cannot be served from the library (unknown instrument,
note too far from every recorded pitch is *not* an error — the nearest
sample is shifted, however far) is reported to the caller so it can fall
back to the synth recipes; a missing library raises
:class:`SampledError`.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np

DATA_DIR = Path(__file__).resolve().parent / "sampled_data"
SAMPLES_DIR = DATA_DIR / "samples"
INDEX_PATH = DATA_DIR / "samples_index.json"

# A sample is not stretched past this: score_render's mastering would
# rather hear a shorter ring than a warped one.  (Samples are long —
# piano ~9 s — so this only bites on very long notes.)
MAX_NOTE_EXTRA_S = 4.0

# Per-instrument release (seconds of fade tail after the note's notated
# end) and how much of the natural decay to keep for short notes.
_RELEASE_S = {
    "piano": 1.2,
    "marimba": 0.5,
    "vibraphone": 0.9,
    "harp": 0.9,
    "glock": 0.7,
    "kalimba": 0.6,
    "wineglass": 0.8,
}
_DEFAULT_RELEASE_S = 0.6

# GM drum name (score_render's vocabulary) -> sampled one-shot instrument.
DRUM_TO_SAMPLED = {
    "kick": "timpani",
    "snare": "slapstick",
    "clap": "slapstick",
    "hat": "woodblock",
    "hat_open": "woodblock",
    "crash": "crash",
}


class SampledError(RuntimeError):
    """Raised when the vendored sample library cannot serve a request."""


@lru_cache(maxsize=1)
def _index() -> dict[str, Any]:
    if not INDEX_PATH.is_file():
        raise SampledError(f"sample index not found: {INDEX_PATH}")
    return json.loads(INDEX_PATH.read_text(encoding="utf-8"))


def available_instruments() -> list[str]:
    """Sorted instrument keys present in the vendored library."""
    return sorted(_index().get("instruments", {}).keys())


def pitched_instruments() -> list[str]:
    """Instruments that can play arbitrary pitches (others are one-shots)."""
    return sorted(
        k for k, v in _index().get("instruments", {}).items() if v.get("pitched")
    )


def _items(instrument: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    insts = _index().get("instruments", {})
    if instrument not in insts:
        raise SampledError(
            f"unknown sampled instrument {instrument!r}; "
            f"available: {', '.join(sorted(insts))}"
        )
    return insts[instrument], list(insts[instrument].get("items", []))


# Velocity-layer values encoded in VCSL file names (upstream mgaudio _VEL).
_VEL = {
    "ppp": 0.12, "pp": 0.2, "p": 0.35, "mp": 0.5, "mf": 0.65, "med": 0.6,
    "medium": 0.6, "f": 0.8, "loud": 0.85, "ff": 0.92, "fff": 1.0,
    "soft": 0.35, "quiet": 0.3, "hard": 0.85, "v1": 0.3, "v2": 0.5,
    "v3": 0.72, "v4": 0.9, "v5": 0.95, "v7": 1.0,
}


def _vel_of(name: str) -> float:
    import re

    toks = re.split(r"[_\-\s]+", name.lower())
    for t in toks:
        if t in _VEL:
            return _VEL[t]
    return 0.7


def _pick_pitched(
    items: list[dict[str, Any]], midi: int, vel01: float
) -> dict[str, Any]:
    """Pure-function pick: nearest pitch, then nearest velocity layer,
    then file name (stable tie-break).  No round-robin state."""
    cands = [i for i in items if i.get("midi") is not None]
    if not cands:
        raise SampledError("instrument has no pitched samples")
    dmin = min(abs(float(i["midi"]) - midi) for i in cands)
    near = [i for i in cands if abs(float(i["midi"]) - midi) <= dmin + 0.6]
    return min(
        near,
        key=lambda i: (
            abs(_vel_of(str(i["name"])) - vel01),
            abs(float(i["midi"]) - midi),
            str(i["file"]),
        ),
    )


def _pick_oneshot(items: list[dict[str, Any]], vel01: float) -> dict[str, Any]:
    if not items:
        raise SampledError("instrument has no samples")
    return min(
        items,
        key=lambda i: (abs(_vel_of(str(i["name"])) - vel01), str(i["file"])),
    )


def _align_pair(x: np.ndarray, sr: int) -> np.ndarray:
    """Align a spaced-pair stereo recording's channels (upstream mgaudio
    ``_align_pair``, numpy-FFT version): shift the lagging channel by the
    lag <= ~1.3 ms that maximises L/R correlation so the mono sum does
    not comb-filter.  Level differences (stereo image) are untouched —
    we only need the mono sum here."""
    maxlag = max(1, int(0.00133 * sr))
    n = min(x.shape[1], sr)
    if n < 4 * maxlag:
        return x
    a = x[0, :n].astype(np.float64)
    b = x[1, :n].astype(np.float64)
    if np.std(a) < 1e-7 or np.std(b) < 1e-7:
        return x
    # cross-correlation via FFT (deterministic)
    nfft = 1 << int(np.ceil(np.log2(2 * n)))
    fa = np.fft.rfft(a, nfft)
    fb = np.fft.rfft(b, nfft)
    xc_full = np.fft.irfft(fa * np.conj(fb), nfft)
    lags = np.concatenate([xc_full[: maxlag + 1], xc_full[-maxlag:]])
    # lags index: 0..maxlag -> lag 0..maxlag ; maxlag+1.. -> lag -maxlag..-1
    k = int(np.argmax(lags))
    lag = k if k <= maxlag else k - (2 * maxlag + 1)
    if lag == 0:
        return x
    centre = lags[maxlag] if maxlag < len(lags) else lags[0]
    if lags[k] <= centre * 1.05:
        return x
    y = x.copy()
    if lag > 0:  # L lags R -> delay R
        y[1, lag:] = x[1, :-lag]
        y[1, :lag] = 0
    else:
        y[0, -lag:] = x[0, :lag]
        y[0, :-lag] = 0
    return y


@lru_cache(maxsize=256)
def _load_mono(relpath: str) -> tuple[np.ndarray, int]:
    """Load a sample as a mono float64 array at its native rate (cached,
    read-only).  Stereo pairs are channel-aligned before summing."""
    import soundfile as sf

    path = SAMPLES_DIR / relpath
    if not path.is_file():
        raise SampledError(f"sample file missing: {relpath}")
    data, sr = sf.read(str(path), dtype="float64", always_2d=True)
    x = data.T  # (channels, n)
    mono = x[0] if x.shape[0] == 1 else _align_pair(x, int(sr)).mean(axis=0)
    mono = np.ascontiguousarray(mono)
    mono.flags.writeable = False
    return mono, int(sr)


def _resample_shift(x: np.ndarray, step: float, out_n: int) -> np.ndarray:
    """Linear-interpolation resample: output sample j reads input at
    j*step.  Deterministic; step>1 raises pitch (and shortens)."""
    if out_n <= 0:
        return np.zeros(0)
    pos = np.arange(out_n, dtype=np.float64) * step
    idx = np.floor(pos).astype(np.int64)
    frac = pos - idx
    idx_c = np.minimum(idx, len(x) - 1)
    nxt = np.minimum(idx + 1, len(x) - 1)
    return x[idx_c] * (1.0 - frac) + x[nxt] * frac


def render_sampled_note(
    instrument: str,
    midi: int,
    dur_s: float,
    vel: int,
    sample_rate: int,
) -> np.ndarray:
    """Play one pitched note from the library; returns a mono float64
    array at ``sample_rate`` lasting ``dur_s`` + a per-instrument release
    tail (or the sample's natural shifted length, if shorter)."""
    meta, items = _items(instrument)
    if not meta.get("pitched"):
        raise SampledError(f"{instrument!r} is a one-shot, not pitched")
    vel01 = float(np.clip(vel / 127.0, 0.0, 1.0))
    item = _pick_pitched(items, midi, vel01)
    x, src_sr = _load_mono(str(item["file"]))
    src_midi = float(item["midi"])
    semis = midi - src_midi
    step = (2.0 ** (semis / 12.0)) * (src_sr / float(sample_rate))
    release = _RELEASE_S.get(instrument, _DEFAULT_RELEASE_S)
    want_s = min(dur_s + release, dur_s + MAX_NOTE_EXTRA_S)
    natural_out = int(len(x) / step)
    out_n = min(int(want_s * sample_rate), natural_out)
    if out_n <= 0:
        raise SampledError(f"sample too short for note: {item['file']}")
    y = _resample_shift(x, step, out_n)
    # gain: per-instrument normalisation (index) x velocity rule
    # (upstream: relative to the picked layer's name velocity).
    layer_vel = max(_vel_of(str(item["name"])), 0.05)
    g = float(meta.get("gain", 0.5)) * float(
        np.clip((vel01 / layer_vel) ** 1.1, 0.35, 2.0)
    ) * (0.35 + 0.65 * vel01)
    y = y * g
    # envelope: tiny attack ramp (some files start mid-waveform), then a
    # squared release fade across the tail after the notated duration.
    n_on = int(dur_s * sample_rate)
    if out_n > n_on:
        r = out_n - n_on
        env = np.ones(out_n)
        env[n_on:] = np.linspace(1.0, 0.0, r) ** 2
        y = y * env
    ramp = min(int(0.001 * sample_rate), out_n)
    if ramp > 0:
        y[:ramp] = y[:ramp] * np.linspace(0.0, 1.0, ramp)
    return y


def render_sampled_oneshot(
    instrument: str, vel: int, sample_rate: int
) -> np.ndarray:
    """Play a one-shot percussion sample at natural pitch; mono float64
    at ``sample_rate``, natural length (resampled if rates differ)."""
    meta, items = _items(instrument)
    vel01 = float(np.clip(vel / 127.0, 0.0, 1.0))
    item = _pick_oneshot(items, vel01)
    x, src_sr = _load_mono(str(item["file"]))
    if src_sr != sample_rate:
        step = src_sr / float(sample_rate)
        y = _resample_shift(x, step, int(len(x) / step))
    else:
        y = x.astype(np.float64).copy()
    layer_vel = max(_vel_of(str(item["name"])), 0.05)
    g = float(meta.get("gain", 0.5)) * float(
        np.clip((vel01 / layer_vel) ** 0.8, 0.4, 1.8)
    )
    y = y * g
    ramp = min(int(0.0003 * sample_rate) + 1, len(y))
    if ramp > 0:
        y[:ramp] = y[:ramp] * np.linspace(0.0, 1.0, ramp)
    return y


def sampled_for_synth_inst(inst: str) -> str | None:
    """Map a score_render synth voice name to a sampled instrument, or
    None when the library has no counterpart (caller keeps the synth)."""
    mapping = {
        "piano": "piano",
        "pluck": "kalimba",
        "strings": "harp",
        "pad": "vibraphone",
        "bass": "piano",
        "sine": "wineglass",
    }
    name = mapping.get(inst)
    if name is None:
        return None
    try:
        _items(name)
    except SampledError:
        return None
    return name


__all__ = [
    "DRUM_TO_SAMPLED",
    "SampledError",
    "available_instruments",
    "pitched_instruments",
    "render_sampled_note",
    "render_sampled_oneshot",
    "sampled_for_synth_inst",
]
