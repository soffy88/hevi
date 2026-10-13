"""Deterministic CPU synthesizers for the W4 sound-effect library.

Every function returns ``(samples, params)`` where ``samples`` is a float64
mono array in ``[-1.0, 1.0]`` at the requested sample rate and ``params`` is a
plain dict that is serialised into ``manifest.json`` under ``source``.

Reproducibility: all randomness flows from one
``numpy.random.Generator(np.random.PCG64(seed))`` passed in by the caller.
There are no global RNG state, no sleeps, no threads. Running the generator
twice with the same seed produces bit-identical WAV bytes.
"""

from __future__ import annotations

import numpy as np
from scipy.signal import lfilter, sosfiltfilt

# ---------------------------------------------------------------------------
# noise + filtering primitives
# ---------------------------------------------------------------------------


def white_noise(rng: np.random.Generator, n: int) -> np.ndarray:
    """Zero-mean unit-variance white noise (deterministic given ``rng``)."""
    return rng.standard_normal(n)


def pink_noise(rng: np.random.Generator, n: int) -> np.ndarray:
    """Paul Kellet refined pink-noise approximation, ~-3 dB/octave.

    Implemented as a bank of six stable first-order IIR sections (each pole
    strictly inside the unit circle) summed with the direct path.  The
    earlier 4-pole ARMA form had poles *outside* the unit circle, so the
    filter diverged and every sample became ``inf``/``nan``; the vectorised
    per-pole ``lfilter`` below is unconditionally stable and depends only on
    ``rng`` and ``n`` (fully deterministic).
    """
    w = white_noise(rng, n)
    poles = (0.99886, 0.99332, 0.96900, 0.86650, 0.55000, -0.7616)
    gains = (0.0555179, 0.0750759, 0.1538520, 0.3104856, 0.5329522, -0.0168980)
    out = 0.5362 * w
    for p, g in zip(poles, gains):
        out = out + lfilter([g], [1.0, -p], w)
    # trailing one-sample-delayed term of the Kellet recurrence
    out[1:] += 0.115926 * w[:-1]
    out -= out.mean()
    return out


def _biquad_bandpass(sr: float, freq: float, q: float):
    """Second-order bandpass SOS for a single centre frequency."""
    f = min(max(freq, sr * 5e-4), sr * 0.2499)
    w = 2.0 * np.pi * f / sr
    alpha = np.sin(w) / (2.0 * q)
    cosw = np.cos(w)
    a0 = 1.0 + alpha
    inv_a0 = 1.0 / a0
    b = np.array([alpha * inv_a0, 0.0, -alpha * inv_a0], dtype=np.float64)
    a = np.array([inv_a0, -2.0 * cosw * inv_a0, (1.0 - alpha) * inv_a0], dtype=np.float64)
    return np.array([[b[0], b[1], b[2], 1.0, a[1], a[2]]], dtype=np.float64)


def bandpass(x: np.ndarray, sr: float, freq: float, q: float) -> np.ndarray:
    """Zero-phase bandpass; safe for short transients (pads symmetrically)."""
    n = x.size
    # A couple of thousand samples is plenty for a 2nd-order section to settle
    # (the old 2**(log2(n)+4) pad reached ~1M samples, which both wasted memory
    # and made the ``[:n]`` slice return the constant edge-pad region instead
    # of the filtered signal -> the output was ~1e-20, i.e. silent).
    pad = min(n, 8192)
    xp = np.pad(x, pad, mode="edge")
    y = sosfiltfilt(_biquad_bandpass(sr, freq, q), xp)
    return y[pad : pad + n]


def sweep_bandpass(
    x: np.ndarray, sr: float, f0: float, f1: float, q: float, k: int = 12
) -> np.ndarray:
    """Linear frequency sweep from ``f0`` to ``f1`` (log interpolation).

    Pre-filters at ``k`` centres and linearly crossfades adjacent pairs along
    the time axis. No chunk boundaries, so there are no comb artefacts.
    """
    if k < 2:
        raise ValueError("k must be >= 2")
    lo, hi = (f0, f1) if f0 <= f1 else (f1, f0)
    freqs = np.geomspace(lo, hi, k)
    stack = np.stack([bandpass(x, sr, float(f), q) for f in freqs])
    n = x.size
    pos = (np.arange(n) / max(n - 1, 1)) * (k - 1)
    i0 = np.minimum(np.floor(pos).astype(np.int64), k - 1)
    i1 = np.minimum(i0 + 1, k - 1)
    frac = pos - i0
    # ``stack`` is (k, n): the frequency-centre index (i0/i1) selects axis 0
    # and the time index (rows) selects axis 1.  Writing ``stack[i0]`` (or
    # ``stack[rows, i0]``) instead broadcasts to an (n, n) array, i.e. ~15.6 GB
    # at 44.1 kHz / 1 s, which is what OOM-killed the earlier runs.
    rows = np.arange(n)
    return stack[i0, rows] * (1.0 - frac) + stack[i1, rows] * frac


def env_linear(n: int) -> np.ndarray:
    t = np.linspace(0.0, 1.0, n)
    return np.clip(t * 8.0, 0.0, 1.0) * np.clip((1.0 - t) * 8.0, 0.0, 1.0)


def env_pinkish(n: int, a: float = 0.35, b: float = 1.6) -> np.ndarray:
    """Asymmetric attack/release envelope (percussive shape)."""
    t = np.linspace(0.0, 1.0, n)
    return t**a * (1.0 - t) ** b


def chirp(t: np.ndarray, sr: float, f0: float, f1: float, shape: str = "exp") -> np.ndarray:
    """Instantaneous-frequency integral -> instantaneous phase (radians)."""
    if shape == "exp":
        tau = max(t[-1] if t[-1] > 0 else 1e-3, 1e-3)
        f = f1 + (f0 - f1) * np.exp(-t / (tau / 3.0))
    elif shape == "lin":
        f = f0 + (f1 - f0) * (t / max(t[-1], 1e-9))
    else:
        raise ValueError(f"unknown chirp shape {shape!r}")
    return 2.0 * np.pi * np.cumsum(f) / sr


def write_wav_int16(path, samples: np.ndarray, sr: int = 44100) -> int:
    """Write mono 16-bit PCM WAV. Returns the number of samples written."""
    import wave

    x = np.clip(samples, -1.0, 1.0)
    raw = np.round(x * 32767.0).astype(np.int16).tobytes()
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(raw)
    return x.size


def clip_duration(samples: np.ndarray, sr: int) -> float:
    return samples.size / float(sr)


# ---------------------------------------------------------------------------
# per-type synthesizers.  Each returns (samples, params).
# ---------------------------------------------------------------------------


def synth_whoosh(
    rng,
    sr: int,
    *,
    dur: float,
    f0: float,
    f1: float,
    q: float,
    noise: str = "pink",
    attack: float = 0.25,
    rel: float = 0.75,
    body: float = 1.0,
    breath: float = 0.0,
) -> tuple:
    """Air movement: bandpass-swept noise with a soft attack/release."""
    n = int(dur * sr)
    t = np.arange(n) / sr
    src = pink_noise(rng, n) if noise == "pink" else white_noise(rng, n)
    sig = sweep_bandpass(src, sr, f0, f1, q, k=14)
    t01 = np.linspace(0.0, 1.0, n)
    env = np.where(
        t01 < attack,
        (t01 / max(attack, 1e-6)) ** 0.7,
        np.maximum((1.0 - t01) / max(rel, 1e-6), 0.0) ** 1.2,
    )
    if breath > 0:
        lfo = 0.5 * (1.0 + np.sin(2.0 * np.pi * 9.0 * t))
        env = env * (1.0 - breath) + env * breath * lfo
    return sig * env * body, {
        "dur": dur,
        "f0": f0,
        "f1": f1,
        "q": q,
        "noise": noise,
        "attack": attack,
        "release": rel,
        "body": body,
        "breath": breath,
    }


def synth_riser(
    rng,
    sr: int,
    *,
    dur: float,
    f_start: float,
    f_end: float,
    tone: float,
    noise: float,
    q: float = 3.5,
    grow: float = 0.75,
    shimmer: float = 0.0,
) -> tuple:
    """Upward tension build: rising chirp + bandpass-swept noise."""
    n = int(dur * sr)
    t = np.arange(n) / sr
    phase = chirp(t, sr, f_start, f_end, shape="lin")
    tone_sig = np.sin(phase) + 0.4 * np.sin(2.0 * phase)
    nz = pink_noise(rng, n)
    noise_sig = sweep_bandpass(nz, sr, f_start * 0.5, max(f_end, f_start * 1.5), q, k=14)
    sig = tone * tone_sig + noise * noise_sig
    t01 = np.linspace(0.0, 1.0, n)
    env = t01**grow
    if shimmer > 0:
        env = env * (1.0 + shimmer * np.sin(2.0 * np.pi * 5.0 * t))
    return sig * env, {
        "dur": dur,
        "f_start": f_start,
        "f_end": f_end,
        "tone": tone,
        "noise": noise,
        "q": q,
        "grow": grow,
        "shimmer": shimmer,
    }


def synth_downer(
    rng,
    sr: int,
    *,
    dur: float,
    f_start: float,
    f_end: float,
    tone: float,
    noise: float,
    q: float = 3.5,
    fall: float = 0.7,
    settle: float = 0.35,
) -> tuple:
    """Downward resolution: descending chirp + falling noise, soft tail."""
    n = int(dur * sr)
    t = np.arange(n) / sr
    phase = chirp(t, sr, f_start, f_end, shape="exp")
    tone_sig = np.sin(phase)
    nz = pink_noise(rng, n)
    noise_sig = sweep_bandpass(nz, sr, f_start, max(f_end, 40.0), q, k=14)
    sig = tone * tone_sig + noise * noise_sig
    t01 = np.linspace(0.0, 1.0, n)
    env = np.maximum((1.0 - t01) / max(fall, 1e-6), 0.0) ** 1.1
    env = env * (1.0 - settle) + settle * np.exp(-t / (dur * 0.45))
    return sig * env, {
        "dur": dur,
        "f_start": f_start,
        "f_end": f_end,
        "tone": tone,
        "noise": noise,
        "q": q,
        "fall": fall,
        "settle": settle,
    }


def synth_impact(
    rng,
    sr: int,
    *,
    dur: float,
    f0: float,
    f1: float,
    decay: float,
    click: float,
    noise: float,
    sub: float = 0.0,
    shape: str = "exp",
) -> tuple:
    """Transient strike: pitch-dropping body + click + noise transient."""
    n = int(dur * sr)
    t = np.arange(n) / sr
    body = np.sin(chirp(t, sr, f0, f1, shape=shape)) * np.exp(-t / max(decay, 1e-6))
    out = body + click * np.exp(-t / 0.004)
    if noise > 0:
        out = out + noise * pink_noise(rng, n) * np.exp(-t / 0.03)
    if sub > 0:
        out = out + sub * np.sin(2.0 * np.pi * (f1 / 2.0) * t) * np.exp(-t / max(decay * 1.6, 1e-6))
    return out, {
        "dur": dur,
        "f0": f0,
        "f1": f1,
        "decay_s": decay,
        "click": click,
        "noise": noise,
        "sub": sub,
        "shape": shape,
    }


def synth_boom(
    rng,
    sr: int,
    *,
    dur: float,
    f0: float,
    f1: float,
    decay: float,
    sub: float,
    noise: float,
    rumble: float,
) -> tuple:
    """Low cinematic explosion: sub body + half-down sub + noise transient."""
    n = int(dur * sr)
    t = np.arange(n) / sr
    env_body = np.exp(-t / max(decay, 1e-6))
    out = np.sin(chirp(t, sr, f0, f1, shape="exp")) * env_body
    out += sub * np.sin(chirp(t, sr, f0 * 0.5, f1 * 0.5, shape="exp")) * env_body
    if noise > 0:
        out += noise * white_noise(rng, n) * np.exp(-t / 0.05)
    if rumble > 0:
        rum = pink_noise(rng, n)
        out += (
            rumble
            * sweep_bandpass(rum, sr, 40.0, 180.0, 1.4, k=10)
            * np.exp(-t / max(decay * 2.0, 1e-6))
        )
    return out, {
        "dur": dur,
        "f0": f0,
        "f1": f1,
        "decay_s": decay,
        "sub": sub,
        "noise": noise,
        "rumble": rumble,
    }


def synth_glitch(
    rng,
    sr: int,
    *,
    dur: float,
    bits: int,
    burst_hz: float,
    stutter: bool,
    bits_crush_gain: float,
    dropout: float,
    rate_hz: float,
) -> tuple:
    """Digital breakage: bit-crushed noise, stutter blocks, dropouts."""
    n = int(dur * sr)
    x = rng.uniform(-1.0, 1.0, n) * bits_crush_gain
    levels = float(2**bits - 1)
    step = 2.0 / max(levels, 1.0)
    x = np.round(x / step) * step
    if stutter:
        blk = max(int(0.012 * sr), 16)
        nb = n // blk
        if nb >= 2:
            idx = rng.integers(0, nb, size=nb)
            blocks = np.zeros(nb, dtype=np.int64)
            for i in range(nb):
                blocks[i] = idx[i % nb] if i % 3 == 0 else i
            y = np.empty(n)
            for i in range(nb):
                s = i * blk
                e = s + blk
                y[s:e] = x[blocks[i] * blk : (blocks[i] + 1) * blk]
            if n - nb * blk:
                y[nb * blk :] = x[nb * blk :]
            x = y
    if dropout > 0:
        nb = max(1, int(dur * rate_hz))
        for i in range(nb):
            c = rng.integers(0, max(n - int(0.008 * sr), 1))
            ln = int(rng.uniform(0.002, 0.010) * sr)
            x[c : c + ln] = 0.0
    out = x * (0.6 + 0.4 * np.sin(2.0 * np.pi * burst_hz * np.arange(n) / sr))
    return out * env_linear(n), {
        "dur": dur,
        "bits": bits,
        "burst_hz": burst_hz,
        "stutter": bool(stutter),
        "bits_crush_gain": bits_crush_gain,
        "dropout": dropout,
        "rate_hz": rate_hz,
    }


def synth_click(
    rng,
    sr: int,
    *,
    dur: float,
    freq: float,
    q: float,
    decay_ms: float,
    resonance: float,
    noise_floor: float,
) -> tuple:
    """Short resonant tick: damped impulse through a bandpass."""
    n = max(int(dur * sr), 16)
    t = np.arange(n) / sr
    imp = np.exp(-t / max(decay_ms / 1000.0, 1e-5))
    sig = bandpass(imp, sr, freq, q)
    if noise_floor > 0:
        nz = white_noise(rng, n)
        sig += noise_floor * bandpass(nz, sr, freq, q * 0.5) * np.exp(-t / 0.01)
    return sig * resonance, {
        "dur": dur,
        "freq": freq,
        "q": q,
        "decay_ms": decay_ms,
        "resonance": resonance,
        "noise_floor": noise_floor,
    }


def synth_pop(
    rng, sr: int, *, dur: float, f0: float, f1: float, decay_ms: float, click: float, wet: float
) -> tuple:
    """Membrane pop: fast pitch slide + click + optional wet tail."""
    n = int(dur * sr)
    t = np.arange(n) / sr
    tau = max(decay_ms / 1000.0, 1e-4)
    body = np.sin(chirp(t, sr, f0, f1, shape="exp")) * np.exp(-t / tau)
    sig = body + click * np.exp(-t / 0.003)
    if wet > 0:
        sig += (
            wet * np.sin(chirp(t, sr, f0 * 0.5, f1 * 0.5, shape="exp")) * np.exp(-t / (tau * 4.0))
        )
    return sig, {"dur": dur, "f0": f0, "f1": f1, "decay_ms": decay_ms, "click": click, "wet": wet}


def synth_ding(
    rng, sr: int, *, dur: float, f0: float, partials, amps, decay_s: float, tremolo_hz: float
) -> tuple:
    """Bell: inharmonic partials with per-partial exponential decay."""
    n = int(dur * sr)
    t = np.arange(n) / sr
    out = np.zeros(n)
    for p, a in zip(partials, amps):
        out += a * np.sin(2.0 * np.pi * f0 * p * t) * np.exp(-t / max(decay_s / max(p, 1e-3), 1e-6))
    if tremolo_hz > 0:
        out *= 1.0 + 0.08 * np.sin(2.0 * np.pi * tremolo_hz * t)
    return out * env_linear(n), {
        "dur": dur,
        "f0": f0,
        "partials": [float(p) for p in partials],
        "amps": [float(a) for a in amps],
        "decay_s": decay_s,
        "tremolo_hz": tremolo_hz,
    }


def synth_chime(
    rng,
    sr: int,
    *,
    dur: float,
    notes,
    note_dur: float,
    decay_s: float,
    gap_s: float,
    partials,
    amps,
) -> tuple:
    """Arpeggiated chime: several short bells placed on a timeline."""
    n = int(dur * sr)
    out = np.zeros(n)
    for i, f0 in enumerate(notes):
        t0 = i * gap_s
        m = int(t0 * sr)
        ln = min(n - m, max(int(note_dur * sr), 8))
        if ln <= 0:
            continue
        tt = np.arange(ln) / sr
        bell = np.zeros(ln)
        for p, a in zip(partials, amps):
            bell += (
                a
                * np.sin(2.0 * np.pi * f0 * p * tt)
                * np.exp(-tt / max(decay_s / max(p, 1e-3), 1e-6))
            )
        out[m : m + ln] += bell * env_linear(ln)
    return out, {
        "dur": dur,
        "notes": [float(x) for x in notes],
        "note_dur_s": note_dur,
        "decay_s": decay_s,
        "gap_s": gap_s,
        "partials": [float(p) for p in partials],
        "amps": [float(a) for a in amps],
    }


def synth_typewriter(
    rng,
    sr: int,
    *,
    dur: float,
    hits,
    jitter_ms: float,
    freq: float,
    q: float,
    decay_ms: float,
    tone: float,
) -> tuple:
    """Mechanical clatter: spaced resonant clacks with slight jitter."""
    n = int(dur * sr)
    out = np.zeros(n)
    for i, base_t in enumerate(hits):
        jt = (rng.uniform(-1.0, 1.0) * jitter_ms / 1000.0) if jitter_ms > 0 else 0.0
        t0 = max(0.0, min(base_t + jt, dur - 0.03))
        m = int(t0 * sr)
        ln = min(n - m, max(int(0.05 * sr), 16))
        tt = np.arange(ln) / sr
        clack = bandpass(np.exp(-tt / max(decay_ms / 1000.0, 1e-5)), sr, freq, q)
        click = np.exp(-tt / 0.003)
        out[m : m + ln] += (
            clack + 0.7 * click + tone * np.sin(2.0 * np.pi * 180.0 * tt) * np.exp(-tt / 0.02)
        )
    return out * env_linear(n), {
        "dur": dur,
        "hits": [round(float(h), 4) for h in hits],
        "jitter_ms": jitter_ms,
        "freq": freq,
        "q": q,
        "decay_ms": decay_ms,
        "tone": tone,
    }


def synth_shutter(
    rng, sr: int, *, dur: float, clicks, tones, mirror_t: float, mirror_f: float
) -> tuple:
    """Camera shutter: sequenced mechanical clicks + mirror slap."""
    n = int(dur * sr)
    out = np.zeros(n)
    for i, (t0, freq, q, amp) in enumerate(clicks):
        m = int(t0 * sr)
        ln = min(n - m, max(int(0.03 * sr), 16))
        tt = np.arange(ln) / sr
        out[m : m + ln] += amp * bandpass(np.exp(-tt / 0.006), sr, freq, q) + 0.5 * amp * np.exp(
            -tt / 0.002
        )
    for f in tones:
        out += (
            0.15 * np.sin(2.0 * np.pi * f * np.arange(n) / sr) * np.exp(-np.arange(n) / sr / 0.04)
        )
    m = int(mirror_t * sr)
    if m < n:
        ln = min(n - m, max(int(0.05 * sr), 16))
        tt = np.arange(ln) / sr
        out[m : m + ln] += 0.6 * bandpass(np.exp(-tt / 0.012), sr, mirror_f, 2.0)
    return out * env_linear(n), {
        "dur": dur,
        "clicks": [[float(t0), float(f), float(q), float(a)] for t0, f, q, a in clicks],
        "tones": [float(f) for f in tones],
        "mirror_t": mirror_t,
        "mirror_f": mirror_f,
    }


def synth_heartbeat(
    rng,
    sr: int,
    *,
    dur: float,
    rate_bpm: float,
    lub_t: float,
    dub_t: float,
    f0: float,
    f1: float,
    lub_gain: float,
    dub_gain: float,
    jitter_ms: float,
) -> tuple:
    """Cardiac pulse: lub-dub pairs repeated at ``rate_bpm``."""
    n = int(dur * sr)
    out = np.zeros(n)
    beat_s = 60.0 / max(rate_bpm, 1.0)
    while True:
        start = rng.uniform(-jitter_ms, jitter_ms) / 1000.0
        beats = 0
        for b in range(int(np.ceil(dur / beat_s)) + 1):
            base = b * beat_s + start
            for off, gain, sc in ((lub_t, lub_gain, 1.0), (dub_t, dub_gain, 0.8)):
                t0 = base + off
                if t0 < 0 or t0 >= dur:
                    continue
                m = int(t0 * sr)
                ln = min(n - m, max(int(0.11 * sr), 16))
                tt = np.arange(ln) / sr
                thump = np.sin(chirp(tt, sr, f0 * sc, f1 * sc, shape="exp")) * np.exp(-tt / 0.055)
                out[m : m + ln] += gain * thump
            beats += 1
        if beats:
            break
    return out * env_linear(n), {
        "dur": dur,
        "rate_bpm": rate_bpm,
        "lub_t": lub_t,
        "dub_t": dub_t,
        "f0": f0,
        "f1": f1,
        "lub_gain": lub_gain,
        "dub_gain": dub_gain,
        "jitter_ms": jitter_ms,
    }


def synth_swipe(
    rng,
    sr: int,
    *,
    dur: float,
    f0: float,
    f1: float,
    q: float,
    attack_ms: float,
    release_ms: float,
    noise: str,
) -> tuple:
    """UI swipe: very fast filtered-noise transient, hard edges."""
    n = int(dur * sr)
    t = np.arange(n) / sr
    src = pink_noise(rng, n) if noise == "pink" else white_noise(rng, n)
    sig = sweep_bandpass(src, sr, f0, f1, q, k=10)
    env = np.ones(n)
    a = max(int(attack_ms / 1000.0 * sr), 1)
    r = max(int(release_ms / 1000.0 * sr), 1)
    env[:a] = np.linspace(0.0, 1.0, a)
    env[-r:] = np.linspace(1.0, 0.0, r) ** 1.5
    return sig * env, {
        "dur": dur,
        "f0": f0,
        "f1": f1,
        "q": q,
        "attack_ms": attack_ms,
        "release_ms": release_ms,
        "noise": noise,
    }


def synth_sparkle(
    rng,
    sr: int,
    *,
    dur: float,
    notes,
    note_dur: float,
    gap_s: float,
    decay_s: float,
    shimmer: float,
    shimmer_f0: float,
    shimmer_f1: float,
) -> tuple:
    """Magic sparkle: high bells + bandpass-swept noise shimmer."""
    n = int(dur * sr)
    out = np.zeros(n)
    parts = (1.0, 2.76, 5.40)
    amps = (1.0, 0.45, 0.2)
    for i, f0 in enumerate(notes):
        m = int(i * gap_s * sr)
        ln = min(n - m, max(int(note_dur * sr), 16))
        if ln <= 0:
            continue
        tt = np.arange(ln) / sr
        bell = np.zeros(ln)
        for p, a in zip(parts, amps):
            bell += (
                a
                * np.sin(2.0 * np.pi * f0 * p * tt)
                * np.exp(-tt / max(decay_s / max(p, 1e-3), 1e-6))
            )
        out[m : m + ln] += bell * env_linear(ln)
    if shimmer > 0:
        nz = white_noise(rng, n)
        out += (
            shimmer
            * sweep_bandpass(nz, sr, shimmer_f0, shimmer_f1, 6.0, k=14)
            * np.linspace(0.0, 1.0, n) ** 0.6
        )
    return out * env_linear(n), {
        "dur": dur,
        "notes": [float(x) for x in notes],
        "note_dur_s": note_dur,
        "gap_s": gap_s,
        "decay_s": decay_s,
        "shimmer": shimmer,
        "shimmer_f0": shimmer_f0,
        "shimmer_f1": shimmer_f1,
    }


def synth_bassdrop(
    rng,
    sr: int,
    *,
    dur: float,
    build_s: float,
    f_build0: float,
    f_build1: float,
    f_body: float,
    f_tail: float,
    body_decay_s: float,
    noise: float,
) -> tuple:
    """Electronic drop: short noise build, then sub sine falling."""
    n = int(dur * sr)
    t = np.arange(n) / sr
    out = np.zeros(n)
    nb = int(build_s * sr)
    if nb > 0:
        nz = pink_noise(rng, nb)
        out[:nb] += (
            noise
            * sweep_bandpass(nz, sr, f_build0, f_build1, 4.0, k=12)
            * np.linspace(0.0, 1.0, nb) ** 0.8
        )
    tb = np.arange(n - nb) / sr if n > nb else np.zeros(0)
    if tb.size:
        body = np.sin(chirp(tb, sr, f_body, f_tail, shape="exp")) * np.exp(
            -tb / max(body_decay_s, 1e-6)
        )
        body += (
            0.5
            * np.sin(chirp(tb, sr, f_body * 0.5, f_tail * 0.5, shape="exp"))
            * np.exp(-tb / max(body_decay_s * 1.6, 1e-6))
        )
        out[nb:] += body
    return out * env_linear(n), {
        "dur": dur,
        "build_s": build_s,
        "f_build0": f_build0,
        "f_build1": f_build1,
        "f_body": f_body,
        "f_tail": f_tail,
        "body_decay_s": body_decay_s,
        "noise": noise,
    }


def synth_notification(
    rng, sr: int, *, dur: float, notes, decay_ms: float, attack_ms: float, detune: float, sub: float
) -> tuple:
    """Device notification: pure tones with fast attack and detune."""
    n = int(dur * sr)
    out = np.zeros(n)
    t = np.arange(n) / sr
    for f0, f1, on, off in notes:
        m = int(on * sr)
        ln = min(n - m, max(int((off - on) * sr), 16))
        if ln <= 0:
            continue
        tt = np.arange(ln) / sr
        env = np.ones(ln)
        a = max(int(attack_ms / 1000.0 * sr), 1)
        r = max(int(decay_ms / 1000.0 * sr), 1)
        env[:a] = np.linspace(0.0, 1.0, a)
        env[-r:] = np.linspace(1.0, 0.0, r)
        sig = np.sin(2.0 * np.pi * (f0 + (f1 - f0) * tt / ln) * tt) * env
        if detune:
            sig += 0.35 * np.sin(2.0 * np.pi * (f0 + detune) * tt) * env
        out[m : m + ln] += sig
    if sub > 0:
        out += sub * np.sin(2.0 * np.pi * 140.0 * t) * np.exp(-t / 0.15)
    return out * env_linear(n), {
        "dur": dur,
        "notes": [[float(f0), float(f1), float(on), float(off)] for f0, f1, on, off in notes],
        "decay_ms": decay_ms,
        "attack_ms": attack_ms,
        "detune": detune,
        "sub": sub,
    }


SYNTHS = {
    "whoosh": synth_whoosh,
    "swoosh": synth_whoosh,
    "riser": synth_riser,
    "downer": synth_downer,
    "impact": synth_impact,
    "boom": synth_boom,
    "glitch": synth_glitch,
    "click": synth_click,
    "tick": synth_click,
    "pop": synth_pop,
    "ding": synth_ding,
    "chime": synth_chime,
    "typewriter": synth_typewriter,
    "shutter": synth_shutter,
    "heartbeat": synth_heartbeat,
    "swipe": synth_swipe,
    "sparkle": synth_sparkle,
    "bassdrop": synth_bassdrop,
    "notification": synth_notification,
}
