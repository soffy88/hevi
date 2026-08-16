"""procedural_bgm 单元测试:确定性合成、拍点均匀、mood 全覆盖、落盘格式。"""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np
import pytest

from hevi.audio.procedural_bgm import (
    MOOD_PRESETS,
    BgmConfig,
    generate_bgm_file,
    synthesize_bgm,
)


@pytest.mark.parametrize("mood", sorted(MOOD_PRESETS))
def test_every_mood_synthesizes(mood: str) -> None:
    cfg = BgmConfig(mood=mood, duration_s=8.0, seed=1)
    samples, grid = synthesize_bgm(cfg)
    assert samples.ndim == 1 and len(samples) > 0
    peak = float(np.max(np.abs(samples)))
    rms = float(np.sqrt(np.mean(samples**2)))
    assert peak > 0.05, f"{mood} 峰值过低"
    assert rms > 0.005, f"{mood} 过静"
    dur = len(samples) / 44100
    bar = 4 * 60 / grid.bpm
    # 向上取整到整小节(不切断和弦),且不超一个小节余量
    assert dur >= 8.0 and dur < 8.0 + bar


def test_beat_grid_uniform_and_periodic() -> None:
    cfg = BgmConfig(mood="calm", duration_s=8.0)
    _, grid = synthesize_bgm(cfg)
    assert grid.beat_count > 0
    assert grid.period_s == pytest.approx(60.0 / grid.bpm)
    for i in range(len(grid.beat_times) - 1):
        assert abs(grid.beat_times[i + 1] - grid.beat_times[i] - grid.period_s) < 1e-9


def test_deterministic_seed() -> None:
    a, _ = synthesize_bgm(BgmConfig(mood="epic", duration_s=6.0, seed=7))
    b, _ = synthesize_bgm(BgmConfig(mood="epic", duration_s=6.0, seed=7))
    assert np.array_equal(a, b)


def test_generate_bgm_file_writes_wav(tmp_path: Path) -> None:
    out, grid = generate_bgm_file(BgmConfig(mood="warm", duration_s=6.0), tmp_path / "bgm.wav")
    assert out.exists() and out.stat().st_size > 1000
    with wave.open(str(out)) as w:
        assert w.getnchannels() == 1
        assert w.getframerate() == 44100
        expected = grid.beat_count / 4 * (60 / grid.bpm) * 4
        assert w.getnframes() / 44100 == pytest.approx(expected, rel=0.05)


def test_invalid_mood_rejected() -> None:
    with pytest.raises(ValueError, match="unknown mood"):
        synthesize_bgm(BgmConfig(mood="nope"))
