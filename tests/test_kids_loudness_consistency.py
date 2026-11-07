"""一致性测试：kids_gate.check_loudness 与 earshot measure 同源同值。

check_loudness 已改为优先调用 hevi.audio.earshot_client.measure 取数、
只做幼儿档阈值判定。立体声样本上两条路径测得的 LUFS/真峰值应在容差内
一致，且 kids_gate 报告须标明测量来源 loudness_source == "earshot"。

已知 earshot 加载器对单声道按双声道复制计量（BS.1770 能量翻倍，
LUFS 恒 +3.01、真峰值不变），kids_gate 对单声道做 -3.01 LU 校正与
ebur128 标定对齐 — 第二个测试把这条校正钉住防回归。
earshot 不可用时跳过（kids_gate 会回落 ebur128，一致性前提不成立）。
"""

from __future__ import annotations

import math
import wave
from pathlib import Path

import pytest

from hevi.audio import earshot_client
from hevi.quality.kids_gate import check_loudness


def _wav(path: Path, *, channels: int, amp: float = 0.2, seconds: float = 3.0) -> Path:
    sr = 48000
    n = int(sr * seconds)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(sr)
        for i in range(n):
            v = int(amp * math.sin(2.0 * math.pi * 440.0 * i / sr) * 32767)
            for _ in range(channels):
                w.writeframes(v.to_bytes(2, "little", signed=True))
    return path


def _measure_or_skip(path: Path) -> dict:
    try:
        return earshot_client.measure(path)
    except earshot_client.EarshotError:
        pytest.skip("earshot not available on this host")


def test_kids_loudness_matches_earshot_measure(tmp_path: Path) -> None:
    wav = _wav(tmp_path / "tone_stereo.wav", channels=2)
    m = _measure_or_skip(wav)

    res = check_loudness(wav)
    assert res.metrics["loudness_source"] == "earshot"
    assert abs(res.metrics["integrated_lufs"] - float(m["lufs"])) <= 0.5
    assert abs(res.metrics["true_peak_dbtp"] - float(m["true_peak_dbtp"])) <= 0.5


def test_kids_loudness_mono_correction(tmp_path: Path) -> None:
    wav = _wav(tmp_path / "tone_mono.wav", channels=1)
    m = _measure_or_skip(wav)

    res = check_loudness(wav)
    assert res.metrics["loudness_source"] == "earshot"
    expected = float(m["lufs"]) - 10.0 * math.log10(2.0)
    assert abs(res.metrics["integrated_lufs"] - expected) <= 0.5
    assert abs(res.metrics["true_peak_dbtp"] - float(m["true_peak_dbtp"])) <= 0.5
