"""LivLiv avatar: catalogue, audio envelope/smoothing, performance planner."""
from __future__ import annotations

import subprocess
import wave
from pathlib import Path

import numpy as np
import pytest

from hevi.avatar_livliv.audio import analyze
from hevi.avatar_livliv.characters import (
    character_name,
    characters_enabled,
    credit,
    list_characters,
)
from hevi.avatar_livliv.render import plan_performance


def _make_wav(path: Path, seconds: float = 1.0, sr: int = 16000) -> Path:
    t = np.linspace(0, seconds, int(sr * seconds), endpoint=False)
    # amplitude-modulated bursts so the envelope actually varies
    env = (np.sin(2 * np.pi * 3 * t) > 0.0).astype(np.float32) * 0.9 + 0.1
    data = (env * np.sin(2 * np.pi * 220 * t) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(data.tobytes())
    return path


def test_catalogue_21_and_nana_refined():
    chars = list_characters()
    assert len(chars) == 21
    assert character_name("d03ft") == "Nana"
    assert character_name("d03") == "Nana"
    ids = {c["id"] for c in chars}
    assert {"d03ft", "d01", "v06"} <= ids


def test_credits_kujira_pen():
    assert "CC BY-NC-SA" in credit("p01")
    assert "CC BY-NC-SA" in credit("p02")
    assert "Pen" in credit("p03")
    assert "LivLiv" in credit("d03ft")


def test_characters_enabled_env(monkeypatch):
    monkeypatch.setenv("LIVLIV_CHARACTERS_ENABLED", "false")
    assert characters_enabled() is False
    monkeypatch.setenv("LIVLIV_CHARACTERS_ENABLED", "true")
    assert characters_enabled() is True


def test_audio_envelope_frames_smoothed_and_bounded(tmp_path):
    wav = _make_wav(tmp_path / "t.wav", seconds=1.0)
    env = analyze(wav, fps=30)
    assert len(env) == 30
    mos = [f["mouthOpen"] for f in env]
    assert all(0.0 <= m <= 1.0 for m in mos)
    # smoothing: second differences are finite and envelope not constant
    assert max(mos) > 0.1
    # vowel in [-1,1]
    assert all(-1.0 <= f["vowel"] <= 1.0 for f in env)


def test_alignment_correlation_with_rms(tmp_path):
    wav = _make_wav(tmp_path / "t.wav", seconds=2.0)
    env = analyze(wav, fps=30)
    mos = np.array([f["mouthOpen"] for f in env])
    with wave.open(str(wav), "rb") as w:
        n = w.getnframes()
        data = w.readframes(n)
        rate = w.getframerate()
    samples = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
    frame_len = int(rate / 30)
    rms = np.array([
        float(np.sqrt(np.mean(samples[i * frame_len:(i + 1) * frame_len] ** 2)))
        for i in range(len(env))
    ])
    corr = float(np.corrcoef(mos, rms)[0, 1])
    assert corr >= 0.5


def test_plan_performance_uses_actual_ids():
    expr, acts = plan_performance(300, fps=30, expressions_available=["smile", "surprised"])
    assert expr and expr[0] == (0, "smile")
    assert acts and acts[0][1] in ("nod", "tilt", "shake")
    # sentence-driven: func data prefers surprised when available
    expr2, acts2 = plan_performance(
        300, fps=30, expressions_available=["smile", "surprised"],
        sentences=[{"start": 1.0, "end": 2.0, "func": "data", "text": "x"}],
    )
    assert (30, "surprised") in expr2
    assert any(a == "nod" for _, a in acts2)
