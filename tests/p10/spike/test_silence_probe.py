"""G0.2 ffmpeg 探测:320ms 静音分辨力 + 版本 pin + 反向(短静音不误报)。"""

import pytest

from hevi.verdict.silence_probe import (
    SilenceProbeFailed,
    ffmpeg_version,
    probe_silence_resolution,
)


def test_ffmpeg_version_pinned(tmp_path):
    version = ffmpeg_version()
    assert "ffmpeg version" in version  # pin 进 receipt 的版本串非空
    (tmp_path / "ffmpeg_version.txt").write_text(version, encoding="utf-8")


def test_probe_resolves_320ms_silence(tmp_path):
    result = probe_silence_resolution(tmp_path, silence_ms=320)
    assert "ffmpeg version" in result.ffmpeg_version
    assert result.detected, f"320ms silence not resolved: {result}"
    assert len(result.events) == 1


def test_reverse_shorter_silence_not_detected_as_320ms(tmp_path):
    # 100ms 静音在 d=320ms 门限下不得报出 320ms 级事件(无幻觉 PASS)
    result = probe_silence_resolution(tmp_path, silence_ms=100)
    assert not result.detected or all(d < 0.32 - 0.08 for _, d in result.events)


def test_reverse_missing_binary_is_fail_loud(monkeypatch):
    import hevi.verdict.silence_probe as probe

    def _boom(*args, **kwargs):
        raise FileNotFoundError("no ffmpeg")

    monkeypatch.setattr(probe.subprocess, "run", _boom)
    with pytest.raises(SilenceProbeFailed):
        ffmpeg_version()
