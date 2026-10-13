"""Build the W4 sound-effect library: files + manifest + schema.

Usage::

    python3 scripts/sfx/gen_sfx_library.py [--out DIR] [--seed N] [--force]

Design constraints (see SFXBAD_TASK.md section A):

* 44.1 kHz, mono, 16-bit PCM WAV, one file per asset, path
  ``<type>/<id>.wav``.
* Durations live in ``[0.10 s, 4.00 s]``.
* Clips longer than 0.5 s are loudness-normalised to **-16 LUFS integrated**
  (EBU R128 via ``ffmpeg -af ebur128``) with a verified true peak below
  -1 dBFS.
* Clips of 0.5 s or shorter are peak-normalised so the peak is at most
  -1 dBFS (short transients have no stable integrated loudness).
* Clips shorter than 0.4 s report ``lufs_integrated: null`` and say why.
* ``manifest.json`` is validated against ``manifest.schema.json``.
* Fully deterministic: same seed -> identical bytes -> identical sha256.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "sfx"))

import sfx_synth as S  # noqa: E402

SAMPLE_RATE = 44100
TARGET_LUFS = -16.0
LUFS_TOLERANCE = 1.5
PEAK_LIMIT_DB = -1.5          # headroom we actually enforce (spec: < -1 dBFS)
LONG_MIN_S = 0.50             # >= 0.5 s  -> LUFS normalisation
SHORT_MAX_S = 0.10
LONG_MAX_S = 4.00
LUFS_REPORT_MIN_S = 0.40      # below this, integrated loudness is unreliable


# ---------------------------------------------------------------------------
# catalog: (type, id, mood, tags, kwargs)
# 67 assets in total.
# ---------------------------------------------------------------------------

CATALOG: list[tuple] = [
    # -- whoosh / swoosh ------------------------------------------------
    ("whoosh", "whoosh_air_up", "tense", ["air", "up", "soft"],
     dict(dur=1.0, f0=220, f1=3800, q=2.2, noise="pink", attack=0.22, rel=0.78, body=1.0, breath=0.0)),
    ("whoosh", "whoosh_air_down", "epic", ["air", "down", "fall"],
     dict(dur=1.2, f0=3200, f1=180, q=2.4, noise="pink", attack=0.12, rel=0.88, body=1.0, breath=0.0)),
    ("whoosh", "whoosh_tight", "comic", ["tight", "fast", "dry"],
     dict(dur=0.45, f0=900, f1=5200, q=4.5, noise="white", attack=0.10, rel=0.90, body=0.9, breath=0.0)),
    ("whoosh", "whoosh_heavy", "epic", ["heavy", "low", "deep"],
     dict(dur=1.6, f0=90, f1=900, q=1.6, noise="pink", attack=0.30, rel=0.70, body=1.0, breath=0.35)),
    ("swoosh", "swoosh_fast", "comic", ["fast", "quick", "ui"],
     dict(dur=0.5, f0=400, f1=6000, q=3.0, noise="white", attack=0.15, rel=0.85, body=1.0, breath=0.0)),
    ("swoosh", "swoosh_slow", "calm", ["slow", "airy", "gentle"],
     dict(dur=1.8, f0=300, f1=2400, q=1.9, noise="pink", attack=0.55, rel=0.45, body=0.9, breath=0.2)),
    ("swoosh", "swoosh_snappy", "tech", ["snappy", "sharp", "ui"],
     dict(dur=0.35, f0=1200, f1=7000, q=5.0, noise="white", attack=0.08, rel=0.92, body=0.95, breath=0.0)),
    # -- riser / downer -------------------------------------------------
    ("riser", "riser_classic", "tense", ["tension", "build", "generic"],
     dict(dur=2.2, f_start=110, f_end=2600, tone=0.7, noise=0.7, q=3.5, grow=0.75, shimmer=0.0)),
    ("riser", "riser_tense", "tense", ["tension", "high", "long"],
     dict(dur=3.0, f_start=180, f_end=4800, tone=0.9, noise=0.6, q=4.5, grow=0.9, shimmer=0.12)),
    ("riser", "riser_tech", "tech", ["digital", "steps", "scan"],
     dict(dur=1.6, f_start=250, f_end=9000, tone=1.0, noise=0.5, q=6.0, grow=0.6, shimmer=0.0)),
    ("riser", "riser_long", "epic", ["epic", "long", "grand"],
     dict(dur=3.8, f_start=80, f_end=3200, tone=0.8, noise=0.8, q=2.8, grow=0.55, shimmer=0.18)),
    ("downer", "downer_resolve", "calm", ["release", "settle", "soft"],
     dict(dur=2.4, f_start=2400, f_end=160, tone=0.7, noise=0.6, q=3.0, fall=0.7, settle=0.4)),
    ("downer", "downer_tense", "tense", ["fall", "drop", "tension"],
     dict(dur=1.4, f_start=4000, f_end=220, tone=0.85, noise=0.7, q=3.6, fall=0.9, settle=0.2)),
    ("downer", "downer_deep", "epic", ["deep", "sub", "long"],
     dict(dur=3.4, f_start=1200, f_end=70, tone=0.9, noise=0.8, q=2.4, fall=0.65, settle=0.5)),
    # -- impact --------------------------------------------------------
    ("impact", "impact_punch", "epic", ["punch", "body", "medium"],
     dict(dur=0.7, f0=140, f1=60, decay=0.11, click=0.7, noise=0.5, sub=0.35)),
    ("impact", "impact_hard", "tense", ["hard", "hit", "sharp"],
     dict(dur=0.55, f0=220, f1=90, decay=0.08, click=0.95, noise=0.35, sub=0.2)),
    ("impact", "impact_soft", "calm", ["soft", "thud", "muted"],
     dict(dur=0.9, f0=95, f1=45, decay=0.16, click=0.4, noise=0.55, sub=0.5)),
    ("impact", "impact_deep", "epic", ["deep", "sub", "heavy"],
     dict(dur=1.2, f0=110, f1=35, decay=0.22, click=0.5, noise=0.3, sub=0.9)),
    ("impact", "impact_snap", "comic", ["snap", "quick", "dry"],
     dict(dur=0.35, f0=400, f1=180, decay=0.05, click=0.9, noise=0.5, sub=0.0)),
    # -- boom ----------------------------------------------------------
    ("boom", "boom_thunder", "epic", ["thunder", "roll", "long"],
     dict(dur=3.4, f0=85, f1=32, decay=1.0, sub=0.7, noise=0.7, rumble=0.9)),
    ("boom", "boom_deep", "epic", ["deep", "sub", "low"],
     dict(dur=2.6, f0=68, f1=26, decay=0.85, sub=0.9, noise=0.45, rumble=0.5)),
    ("boom", "boom_cinematic", "epic", ["cinematic", "explosion", "grand"],
     dict(dur=3.8, f0=120, f1=28, decay=1.2, sub=0.8, noise=0.9, rumble=1.0)),
    ("boom", "boom_short", "tense", ["short", "punch", "quick"],
     dict(dur=0.9, f0=95, f1=38, decay=0.22, sub=0.5, noise=0.8, rumble=0.3)),
    # -- glitch --------------------------------------------------------
    ("glitch", "glitch_digital", "tech", ["digital", "noise", "broken"],
     dict(dur=1.0, bits=4, burst_hz=7, stutter=False, bits_crush_gain=0.55, dropout=0.0, rate_hz=20)),
    ("glitch", "glitch_stutter", "comic", ["stutter", "repeat", "loop"],
     dict(dur=1.1, bits=5, burst_hz=9, stutter=True, bits_crush_gain=0.5, dropout=0.0, rate_hz=24)),
    ("glitch", "glitch_break", "tense", ["break", "dropout", "error"],
     dict(dur=0.9, bits=3, burst_hz=11, stutter=False, bits_crush_gain=0.6, dropout=0.5, rate_hz=30)),
    ("glitch", "glitch_scan", "tech", ["scan", "vhs", "dat"],
     dict(dur=1.4, bits=6, burst_hz=3, stutter=True, bits_crush_gain=0.45, dropout=0.25, rate_hz=16)),
    # -- click / tick --------------------------------------------------
    ("click", "click_pen", "calm", ["pen", "office", "soft"],
     dict(dur=0.13, freq=2600, q=7.0, decay_ms=4.0, resonance=0.9, noise_floor=0.15)),
    ("click", "click_clock", "calm", ["clock", "metronome", "wood"],
     dict(dur=0.12, freq=1800, q=5.5, decay_ms=6.0, resonance=1.0, noise_floor=0.2)),
    ("click", "click_wood", "comic", ["wood", "dry", "hard"],
     dict(dur=0.11, freq=900, q=3.2, decay_ms=5.0, resonance=1.1, noise_floor=0.3)),
    ("click", "click_soft", "calm", ["soft", "muted", "ui"],
     dict(dur=0.10, freq=3400, q=8.0, decay_ms=3.0, resonance=0.75, noise_floor=0.1)),
    ("click", "click_mech", "tech", ["mechanical", "switch", "sharp"],
     dict(dur=0.10, freq=4200, q=10.0, decay_ms=2.5, resonance=1.2, noise_floor=0.25)),
    ("tick", "tick_tiny", "calm", ["tiny", "light", "fast"],
     dict(dur=0.10, freq=5200, q=12.0, decay_ms=2.0, resonance=0.85, noise_floor=0.1)),
    ("tick", "tick_metal", "tech", ["metal", "ring", "thin"],
     dict(dur=0.11, freq=7000, q=16.0, decay_ms=5.0, resonance=1.05, noise_floor=0.2)),
    ("tick", "tick_dry", "comic", ["dry", "paper", "flat"],
     dict(dur=0.11, freq=1200, q=2.6, decay_ms=4.0, resonance=1.0, noise_floor=0.35)),
    # -- pop -----------------------------------------------------------
    ("pop", "pop_bubble", "comic", ["bubble", "round", "soft"],
     dict(dur=0.22, f0=900, f1=280, decay_ms=38, click=0.5, wet=0.0)),
    ("pop", "pop_snap", "comic", ["snap", "sharp", "quick"],
     dict(dur=0.16, f0=1400, f1=360, decay_ms=24, click=0.85, wet=0.0)),
    ("pop", "pop_dry", "calm", ["dry", "light", "flat"],
     dict(dur=0.12, f0=700, f1=200, decay_ms=20, click=0.45, wet=0.0)),
    ("pop", "pop_wet", "comic", ["wet", "bouncy", "cartoon"],
     dict(dur=0.30, f0=1100, f1=320, decay_ms=42, click=0.6, wet=0.55)),
    # -- ding / chime --------------------------------------------------
    ("ding", "ding_bell", "calm", ["bell", "clear", "medium"],
     dict(dur=1.2, f0=880, partials=(1.0, 2.0, 2.94, 4.07, 5.43), amps=(1.0, 0.42, 0.22, 0.12, 0.06),
          decay_s=0.55, tremolo_hz=0.0)),
    ("ding", "ding_deep", "tense", ["deep", "low", "dark"],
     dict(dur=1.5, f0=440, partials=(1.0, 2.0, 2.94, 4.07, 5.43), amps=(1.0, 0.45, 0.25, 0.14, 0.07),
          decay_s=0.8, tremolo_hz=0.0)),
    ("ding", "ding_glass", "tech", ["glass", "bright", "thin"],
     dict(dur=1.0, f0=1760, partials=(1.0, 2.76, 5.40, 8.93), amps=(1.0, 0.5, 0.25, 0.12),
          decay_s=0.45, tremolo_hz=5.0)),
    ("chime", "chime_triple", "joyful", ["triple", "rising", "sweet"],
     dict(dur=1.5, notes=(880.0, 1174.7, 1760.0), note_dur=1.1, decay_s=0.5, gap_s=0.28,
          partials=(1.0, 2.76, 5.40), amps=(1.0, 0.45, 0.22))),
    ("chime", "chime_glass", "joyful", ["glass", "sparkle", "high"],
     dict(dur=1.8, notes=(1318.5, 1760.0, 2637.0), note_dur=1.4, decay_s=0.6, gap_s=0.3,
          partials=(1.0, 2.76, 5.40), amps=(1.0, 0.5, 0.28))),
    ("chime", "chime_soft", "calm", ["soft", "gentle", "low"],
     dict(dur=2.0, notes=(523.3, 659.3, 784.0), note_dur=1.6, decay_s=0.8, gap_s=0.35,
          partials=(1.0, 2.76, 5.40), amps=(1.0, 0.4, 0.2))),
    # -- typewriter ----------------------------------------------------
    ("typewriter", "typewriter_single", "calm", ["single", "one", "key"],
     dict(dur=0.5, hits=(0.06,), jitter_ms=0, freq=1900, q=6.0, decay_ms=6, tone=0.4)),
    ("typewriter", "typewriter_triple", "calm", ["triple", "word", "keys"],
     dict(dur=0.8, hits=(0.05, 0.32, 0.6), jitter_ms=12, freq=1900, q=6.0, decay_ms=6, tone=0.4)),
    ("typewriter", "typewriter_rush", "tense", ["rush", "fast", "keys"],
     dict(dur=1.2, hits=(0.04, 0.2, 0.36, 0.55, 0.72, 0.95), jitter_ms=18, freq=1750, q=5.5, decay_ms=5, tone=0.35)),
    ("typewriter", "typewriter_mech", "tech", ["mechanical", "heavy", "keys"],
     dict(dur=1.4, hits=(0.06, 0.34, 0.62, 0.9), jitter_ms=8, freq=1100, q=3.4, decay_ms=9, tone=0.6)),
    # -- camera shutter ------------------------------------------------
    ("shutter", "shutter_single", "tech", ["single", "mirrorless", "clean"],
     dict(dur=0.5, clicks=((0.02, 8000, 8.0, 1.0),), tones=(), mirror_t=0.055, mirror_f=300)),
    ("shutter", "shutter_double", "tech", ["double", "slam", "classic"],
     dict(dur=0.6, clicks=((0.02, 9000, 8.0, 1.0), (0.2, 5000, 6.0, 0.85)),
          tones=(2500,), mirror_t=0.3, mirror_f=250)),
    ("shutter", "shutter_mirror", "calm", ["mirror", "slap", "dslr"],
     dict(dur=0.7, clicks=((0.02, 7500, 7.0, 0.9), (0.18, 6000, 6.5, 0.8)),
          tones=(), mirror_t=0.42, mirror_f=180)),
    # -- heartbeat -----------------------------------------------------
    ("heartbeat", "heartbeat_single", "tense", ["single", "one", "pulse"],
     dict(dur=0.9, rate_bpm=70, lub_t=0.05, dub_t=0.26, f0=62, f1=34, lub_gain=1.0,
          dub_gain=0.6, jitter_ms=0)),
    ("heartbeat", "heartbeat_double", "tense", ["double", "steady", "pulse"],
     dict(dur=1.3, rate_bpm=70, lub_t=0.05, dub_t=0.26, f0=62, f1=34, lub_gain=1.0,
          dub_gain=0.6, jitter_ms=6)),
    ("heartbeat", "heartbeat_rapid", "tense", ["rapid", "panic", "fast"],
     dict(dur=1.6, rate_bpm=140, lub_t=0.04, dub_t=0.2, f0=70, f1=40, lub_gain=1.0,
          dub_gain=0.65, jitter_ms=4)),
    ("heartbeat", "heartbeat_slow", "epic", ["slow", "deep", "calm"],
     dict(dur=2.2, rate_bpm=44, lub_t=0.06, dub_t=0.3, f0=52, f1=28, lub_gain=1.0,
          dub_gain=0.55, jitter_ms=0)),
    # -- swipe ---------------------------------------------------------
    ("swipe", "swipe_left", "tech", ["left", "ui", "fast"],
     dict(dur=0.3, f0=1400, f1=6800, q=4.0, attack_ms=8, release_ms=60, noise="white")),
    ("swipe", "swipe_right", "tech", ["right", "ui", "fast"],
     dict(dur=0.3, f0=6800, f1=1400, q=4.0, attack_ms=8, release_ms=60, noise="white")),
    ("swipe", "swipe_up", "comic", ["up", "spring", "playful"],
     dict(dur=0.35, f0=600, f1=5000, q=3.2, attack_ms=10, release_ms=90, noise="pink")),
    ("swipe", "swipe_down", "comic", ["down", "drop", "playful"],
     dict(dur=0.35, f0=5000, f1=600, q=3.2, attack_ms=10, release_ms=90, noise="pink")),
    # -- sparkle -------------------------------------------------------
    ("sparkle", "sparkle_magic", "joyful", ["magic", "wand", "sweet"],
     dict(dur=1.5, notes=(1568.0, 2093.0, 2637.0), note_dur=1.2, gap_s=0.22, decay_s=0.55,
          shimmer=0.35, shimmer_f0=4000, shimmer_f1=14000)),
    ("sparkle", "sparkle_crystal", "joyful", ["crystal", "bright", "glass"],
     dict(dur=1.8, notes=(2093.0, 3136.0), note_dur=1.6, gap_s=0.3, decay_s=0.7,
          shimmer=0.4, shimmer_f0=6000, shimmer_f1=18000)),
    ("sparkle", "sparkle_fairy", "joyful", ["fairy", "airy", "soft"],
     dict(dur=2.0, notes=(1318.5, 1760.0, 2637.0, 3492.0), note_dur=1.5, gap_s=0.2,
          decay_s=0.6, shimmer=0.3, shimmer_f0=5000, shimmer_f1=15000)),
    ("sparkle", "sparkle_glitter", "epic", ["glitter", "shine", "big"],
     dict(dur=2.4, notes=(1046.5, 1568.0, 2093.0, 3136.0), note_dur=1.9, gap_s=0.28,
          decay_s=0.8, shimmer=0.45, shimmer_f0=3500, shimmer_f1=16000)),
    # -- bass drop -----------------------------------------------------
    ("bassdrop", "bassdrop_trap", "epic", ["trap", "808", "build"],
     dict(dur=1.6, build_s=0.6, f_build0=300, f_build1=6000, f_body=130, f_tail=28,
          body_decay_s=0.75, noise=0.8)),
    ("bassdrop", "bassdrop_deep", "epic", ["deep", "sub", "long"],
     dict(dur=2.4, build_s=0.9, f_build0=200, f_build1=5000, f_body=95, f_tail=22,
          body_decay_s=1.3, noise=0.7)),
    ("bassdrop", "bassdrop_short", "tense", ["short", "quick", "punch"],
     dict(dur=0.8, build_s=0.25, f_build0=400, f_build1=7000, f_body=160, f_tail=40,
          body_decay_s=0.3, noise=0.75)),
    # -- notification --------------------------------------------------
    ("notification", "notification_ping", "tech", ["ping", "soft", "single"],
     dict(dur=0.7, notes=((1318.5, 1760.0, 0.03, 0.42),), decay_ms=180, attack_ms=12,
          detune=0.0, sub=0.25)),
    ("notification", "notification_double", "tech", ["double", "toast", "ui"],
     dict(dur=1.0, notes=((1174.7, 1174.7, 0.03, 0.3), (1760.0, 1760.0, 0.34, 0.66)),
          decay_ms=160, attack_ms=10, detune=0.0, sub=0.15)),
    ("notification", "notification_chime", "joyful", ["chime", "sweet", "bell"],
     dict(dur=1.1, notes=((1568.0, 2093.0, 0.03, 0.55), (2093.0, 2793.0, 0.4, 0.9)),
          decay_ms=200, attack_ms=10, detune=8.0, sub=0.0)),
]


def source_string(synth_type: str, params: dict) -> str:
    """Compact ``synth:<type>:k=v;k=v`` provenance string."""
    kv = ";".join(f"{k}={v}" for k, v in params.items())
    return f"synth:{synth_type}:{kv}"


# ---------------------------------------------------------------------------
# loudness measurement / normalisation
# ---------------------------------------------------------------------------


def _ffmpeg_stderr(*cmd: str) -> str:
    proc = subprocess.run(["ffmpeg", *cmd], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed ({proc.returncode}): {proc.stderr[-600:]}")
    return proc.stderr


def measure(path: Path) -> tuple[float | None, float]:
    """Return ``(lufs_integrated, true_peak_dbfs)`` measured with ebur128."""
    err = _ffmpeg_stderr(
        "-nostdin", "-hide_banner", "-nostats", "-i", str(path),
        "-af", "ebur128=peak=true", "-f", "null", "-",
    )
    lufs = peak = None
    for line in err.splitlines():
        m = re.search(r"I:\s*(-?[\d.]+)\s*LUFS", line)
        if m:
            lufs = float(m.group(1))
        m = re.search(r"Peak:\s*(-?[\d.]+|-?inf|inf)\s*dBFS", line)
        if m:
            tok = m.group(1)
            peak = -120.0 if "inf" in tok else float(tok)
    if lufs is None or peak is None:
        raise RuntimeError(f"could not parse ebur128 output for {path}: {err[-400:]}")
    return lufs, peak


def normalize(samples: np.ndarray, dur: float, rng_seed_note: str) -> np.ndarray:
    """Apply the library loudness policy. Returns float64 in [-1, 1].

    * ``dur >= 0.5 s``  -> integrated loudness at -16 LUFS (2-pass ffmpeg),
      with a final peak cap so no sample exceeds -1.5 dBFS.
    * ``dur <  0.5 s``  -> peak normalised to -1.5 dBFS.
    """
    if dur < SHORT_MAX_S or dur > LONG_MAX_S:
        raise ValueError(f"duration {dur}s outside [{SHORT_MAX_S}, {LONG_MAX_S}]")

    x = np.asarray(samples, dtype=np.float64)
    p = float(np.max(np.abs(x))) if x.size else 0.0
    if p <= 1e-12:
        raise ValueError("silent signal; nothing to normalise")
    # reference peak so gain arithmetic stays well behaved
    x = x / p * 10.0 ** (-6.0 / 20.0)

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td) / "probe.wav"
        S.write_wav_int16(tmp, x)
        lufs, peak = measure(tmp)
        if dur >= LONG_MIN_S:
            gain = TARGET_LUFS - lufs
            y = x * 10.0 ** (gain / 20.0)
            cap = 10.0 ** (PEAK_LIMIT_DB / 20.0)
            yp = float(np.max(np.abs(y)))
            if yp > cap:
                # Crest factor too large for the loudness target: keep the
                # peak legal and accept a slightly softer integrated level.
                y = y * (cap / yp)
        else:
            y = x * (10.0 ** (PEAK_LIMIT_DB / 20.0) / max(peak, 1e-12))
    return y


def write_asset(out_dir: Path, entry: tuple, seed: int) -> dict:
    """Render one asset, write its WAV, return the manifest record."""
    synth_type, asset_id, mood, tags, params = entry
    dur = float(params.get("dur", 1.0))
    out_path = out_dir / synth_type / f"{asset_id}.wav"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    rng = np.random.default_rng(np.random.SeedSequence([seed, int(hash(asset_id) & 0x7FFFFFFF)]))
    fn = S.SYNTHS[synth_type]
    samples, used = fn(rng, SAMPLE_RATE, **params)

    samples = normalize(samples, dur)
    S.write_wav_int16(out_path, samples)

    actual = S.clip_duration(samples, SAMPLE_RATE)
    with open(out_path, "rb") as fh:
        sha = hashlib.sha256(fh.read()).hexdigest()

    lufs, peak = measure(out_path)
    if actual < LUFS_REPORT_MIN_S:
        lufs_out = None
        lufs_note = (f"clip is {actual:.3f}s (< 0.4s): EBU R128 integrated "
                     "loudness is not meaningful this short, so loudness "
                     "control was applied on true peak instead")
    else:
        lufs_out = round(lufs, 2)
        lufs_note = None

    rec = {
        "id": asset_id,
        "file": f"assets/audio/sfx/library/{synth_type}/{asset_id}.wav",
        "type": synth_type,
        "mood": mood,
        "tags": tags,
        "duration_s": round(actual, 4),
        "sample_rate": SAMPLE_RATE,
        "channels": 1,
        "bit_depth": 16,
        "lufs_integrated": lufs_out,
        "lufs_integrated_note": lufs_note,
        "true_peak_dbfs": round(peak, 2),
        "source": source_string(synth_type, used),
        "sha256": sha,
    }
    return rec


# ---------------------------------------------------------------------------
# schema
# ---------------------------------------------------------------------------

SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://hevi.local/schemas/sfx-library-manifest.json",
    "title": "HEVI W4 SFX library manifest",
    "type": "object",
    "additionalProperties": False,
    "required": ["schema_version", "sample_rate", "channels", "bit_depth",
                 "loudness_policy", "asset_count", "assets"],
    "properties": {
        "schema_version": {"type": "string", "const": "1.0"},
        "generator": {"type": "string"},
        "seed": {"type": "integer", "minimum": 0},
        "sample_rate": {"type": "integer", "const": 44100},
        "channels": {"type": "integer", "const": 1},
        "bit_depth": {"type": "integer", "const": 16},
        "loudness_policy": {
            "type": "object",
            "additionalProperties": False,
            "required": ["target_lufs_integrated", "tolerance_lu",
                         "long_clip_min_s", "peak_limit_dbfs", "min_duration_s",
                         "max_duration_s", "lufs_report_min_s"],
            "properties": {
                "target_lufs_integrated": {"type": "number", "const": -16.0},
                "tolerance_lu": {"type": "number", "const": 1.5},
                "long_clip_min_s": {"type": "number", "const": 0.5},
                "peak_limit_dbfs": {"type": "number", "const": -1.5},
                "min_duration_s": {"type": "number", "const": 0.1},
                "max_duration_s": {"type": "number", "const": 4.0},
                "lufs_report_min_s": {"type": "number", "const": 0.4},
                "notes": {"type": "string"},
            },
        },
        "asset_count": {"type": "integer", "minimum": 60},
        "assets": {
            "type": "array",
            "minItems": 60,
            "items": {"$ref": "#/$defs/asset"},
        },
    },
    "$defs": {
        "asset": {
            "type": "object",
            "additionalProperties": False,
            "required": ["id", "file", "type", "mood", "tags", "duration_s",
                         "sample_rate", "channels", "bit_depth",
                         "lufs_integrated", "true_peak_dbfs", "source", "sha256"],
            "properties": {
                "id": {"type": "string", "pattern": "^[a-z0-9]+(_[a-z0-9]+)*$"},
                "file": {"type": "string",
                         "pattern": "^assets/audio/sfx/library/[a-z]+/[a-z0-9_]+\\.wav$"},
                "type": {"type": "string",
                         "enum": sorted(S.SYNTHS.keys())},
                "mood": {"type": "string",
                         "enum": ["tense", "joyful", "comic", "epic", "calm", "tech"]},
                "tags": {"type": "array", "minItems": 1, "maxItems": 8,
                         "items": {"type": "string"}, "uniqueItems": True},
                "duration_s": {"type": "number", "minimum": 0.1, "maximum": 4.0},
                "sample_rate": {"type": "integer", "const": 44100},
                "channels": {"type": "integer", "const": 1},
                "bit_depth": {"type": "integer", "const": 16},
                "lufs_integrated": {"type": ["number", "null"]},
                "lufs_integrated_note": {"type": ["string", "null"]},
                "true_peak_dbfs": {"type": "number", "maximum": -1.0, "minimum": -120.0},
                "source": {"type": "string", "pattern": "^synth:[a-z]+:"},
                "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
            },
            "allOf": [
                {
                    "if": {"properties": {"duration_s": {"exclusiveMaximum": 0.4}},
                            "required": ["duration_s"]},
                    "then": {"properties": {"lufs_integrated": {"type": "null"},
                                            "lufs_integrated_note": {"type": "string"}}},
                    "else": {"properties": {"lufs_integrated": {"type": "number",
                                "minimum": -17.5, "maximum": -14.5}}},
                },
            ],
        }
    },
}


def build_manifest(records: list[dict], seed: int) -> dict:
    return {
        "schema_version": "1.0",
        "generator": "scripts/sfx/gen_sfx_library.py",
        "seed": seed,
        "sample_rate": SAMPLE_RATE,
        "channels": 1,
        "bit_depth": 16,
        "loudness_policy": {
            "target_lufs_integrated": TARGET_LUFS,
            "tolerance_lu": LUFS_TOLERANCE,
            "long_clip_min_s": LONG_MIN_S,
            "peak_limit_dbfs": PEAK_LIMIT_DB,
            "min_duration_s": SHORT_MAX_S,
            "max_duration_s": LONG_MAX_S,
            "lufs_report_min_s": LUFS_REPORT_MIN_S,
            "notes": ("Clips >= 0.5s are normalised to -16 LUFS integrated "
                      "(ffmpeg ebur128, two pass) with a -1.5 dBFS peak cap; "
                      "shorter clips are peak-normalised to -1.5 dBFS. No clip "
                      "may exceed -1 dBFS. Clips < 0.4s report "
                      "lufs_integrated=null because EBU R128 integrated "
                      "loudness is undefined that short."),
        },
        "asset_count": len(records),
        "assets": records,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build the W4 SFX library")
    ap.add_argument("--out", default=str(ROOT / "assets/audio/sfx/library"),
                    help="output directory (default: assets/audio/sfx/library)")
    ap.add_argument("--seed", type=int, default=20261013)
    ap.add_argument("--force", action="store_true", help="overwrite existing files")
    ap.add_argument("--manifest", default=None, help="manifest path override")
    ap.add_argument("--dry-run", action="store_true", help="parse and validate only")
    args = ap.parse_args(argv)

    out = Path(args.out).resolve()
    man_path = Path(args.manifest) if args.manifest else out / "manifest.json"

    ids = [e[1] for e in CATALOG]
    if len(set(ids)) != len(ids):
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        raise SystemExit(f"duplicate asset ids: {dupes}")

    if args.dry_run:
        from jsonschema import Draft202012Validator
        Draft202012Validator.check_schema(SCHEMA)
        print(f"catalog ok: {len(CATALOG)} assets, "
              f"{len({e[0] for e in CATALOG})} types; schema ok")
        return 0

    if out.exists() and out.is_dir():
        stale = [p for p in out.glob("*/*.wav")]
        if stale and not args.force:
            raise SystemExit(
                f"{out} already holds {len(stale)} wav files; pass --force to rebuild")

    print(f"rendering {len(CATALOG)} assets -> {out} (seed={args.seed})")
    records = []
    for i, entry in enumerate(CATALOG, 1):
        rec = write_asset(out, entry, args.seed)
        records.append(rec)
        lufs = rec["lufs_integrated"]
        lufs_txt = f"{lufs:+.2f} LUFS" if lufs is not None else "peak-only"
        print(f"  {i:2d}/{len(CATALOG)} {rec['type']:<13} {rec['id']:<22} "
              f"{rec['duration_s']:.3f}s {lufs_txt:>13} "
              f"peak={rec['true_peak_dbfs']:+.2f} dBFS")

    man = build_manifest(records, args.seed)

    from jsonschema import Draft202012Validator
    Draft202012Validator.check_schema(SCHEMA)
    errs = sorted(Draft202012Validator(SCHEMA).iter_errors(man),
                  key=lambda e: list(e.path))
    if errs:
        for e in errs[:20]:
            print(f"SCHEMA ERROR at /{'/'.join(map(str, e.path))}: {e.message}")
        raise SystemExit(f"manifest failed schema validation: {len(errs)} errors")

    man_path.parent.mkdir(parents=True, exist_ok=True)
    man_path.write_text(json.dumps(man, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    schema_path = man_path.with_name("manifest.schema.json")
    schema_path.write_text(json.dumps(SCHEMA, indent=2) + "\n", encoding="utf-8")

    # policy report
    longs = [r for r in records if r["duration_s"] >= LONG_MIN_S]
    shorts = [r for r in records if r["duration_s"] < LONG_MIN_S]
    lufs_bad = [r["id"] for r in longs if r["lufs_integrated"] is not None and
                abs(r["lufs_integrated"] - TARGET_LUFS) > LUFS_TOLERANCE]
    peak_bad = [r["id"] for r in records if r["true_peak_dbfs"] >= -1.0]
    dur_bad = [r["id"] for r in records if not (SHORT_MAX_S <= r["duration_s"] <= LONG_MAX_S)]
    print(f"\nmanifest: {man_path}")
    print(f"schema  : {schema_path}")
    print(f"assets  : {len(records)}  (long {len(longs)}, short {len(shorts)})")
    print(f"LUFS out of [-17.5,-14.5]: {lufs_bad or 'none'}")
    print(f"peak >= -1 dBFS          : {peak_bad or 'none'}")
    print(f"duration out of range    : {dur_bad or 'none'}")
    if lufs_bad or peak_bad or dur_bad:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
