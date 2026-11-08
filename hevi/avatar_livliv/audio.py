"""Audio envelope + simple vowel estimate for LivLiv mouthOpen/vowel per frame."""
from __future__ import annotations

import json
import math
import subprocess
import wave
from pathlib import Path
from typing import Any

import numpy as np


def _to_wav(src: Path, dst: Path, sr: int = 16000) -> Path:
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(src), "-vn", "-ac", "1", "-ar", str(sr), str(dst)],
        capture_output=True, check=False,
    )
    return dst


def analyze(audio: Path, fps: int = 30, sr: int = 16000) -> list[dict[str, float]]:
    """Return list of {t, mouthOpen, vowel} per frame for the audio duration."""
    wav = audio.with_suffix(".render.wav")
    if audio.suffix.lower() != ".wav":
        _to_wav(audio, wav, sr)
    else:
        wav = audio
    with wave.open(str(wav), "rb") as w:
        n = w.getnframes()
        channels = w.getnchannels()
        width = w.getsampwidth()
        data = w.readframes(n)
        rate = w.getframerate()
    dtype = {1: np.int8, 2: np.int16, 4: np.int32}.get(width, np.int16)
    samples = np.frombuffer(data, dtype=dtype).astype(np.float32)
    if width == 2:
        samples /= 32768.0
    elif width == 4:
        samples /= 2147483648.0
    elif width == 1:
        samples = (samples - 128.0) / 128.0
    if channels > 1:
        # The koubo pipeline pads the narration to 44.1 kHz stereo before the
        # avatar render; without this downmix the duration doubles and the
        # mouth envelope is read over interleaved samples (lip-sync drift).
        samples = samples.reshape(-1, channels).mean(axis=1)
    dur = len(samples) / rate
    nframes = max(1, int(math.ceil(dur * fps)))
    out = []
    frame_len = int(rate / fps)
    # simple spectral centroid for vowel mapping
    for i in range(nframes):
        start = i * frame_len
        end = min(len(samples), start + frame_len)
        chunk = samples[start:end]
        if len(chunk) == 0:
            out.append({"t": i / fps, "mouthOpen": 0.0, "vowel": 0.0})
            continue
        rms = float(np.sqrt(np.mean(chunk * chunk)))
        # normalize rms to 0..1 with a gentle curve
        mo = min(1.0, max(0.0, rms * 4.0))
        if mo < 0.05:
            mo = 0.0
        spec = np.abs(np.fft.rfft(chunk * np.hanning(len(chunk))))
        freqs = np.fft.rfftfreq(len(chunk), 1.0 / rate)
        c = float(np.sum(freqs * spec) / (np.sum(spec) + 1e-9))
        vowel = (c - 1500.0) / 1500.0
        vowel = max(-1.0, min(1.0, vowel))
        out.append({"t": i / fps, "mouthOpen": round(mo, 4), "vowel": round(vowel, 4)})
    mos = [f["mouthOpen"] for f in out]
    # Smooth with a 3-frame moving average, then advance by 1 frame
    # (mouth slightly before sound; spec: lead 1-2 frames, error <=1 frame).
    smooth = []
    for i in range(len(mos)):
        lo = max(0, i - 1)
        hi = min(len(mos), i + 2)
        smooth.append(sum(mos[lo:hi]) / (hi - lo))
    advanced = smooth[1:] + [0.0] if smooth else []
    for i, f in enumerate(out):
        f["mouthOpen"] = round(float(advanced[i]), 4) if i < len(advanced) else 0.0
    # smooth vowel as well
    vs = [f["vowel"] for f in out]
    if vs:
        for i, f in enumerate(out):
            lo = max(0, i - 1)
            hi = min(len(vs), i + 2)
            f["vowel"] = round(float(sum(vs[lo:hi]) / (hi - lo)), 4)
    return out


def save_envelope(audio: Path, out: Path, fps: int = 30) -> Path:
    env = analyze(audio, fps=fps)
    out.write_text(json.dumps(env, ensure_ascii=False, indent=2), encoding="utf-8")
    return out
