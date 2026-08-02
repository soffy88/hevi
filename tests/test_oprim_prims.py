"""3O §2 Task 2.2:oprim 原子 prim(edge_tts_word_boundary / probe_duration)单测。

这些 prim 由 scripts/patch_oprim_prims.py 注入已安装的 oprim(git-pinned),
升级 oprim 后需上游合入 helios-plat/oprim。此处锁定原子行为契约。
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest
from oprim import edge_tts_word_boundary, probe_duration
from oprim._edge_tts_word_boundary import EdgeTtsWordBoundaryError


def _install_fake_edge_tts() -> None:
    """假的 edge_tts:stream() 产出音频 + WordBoundary 块(100ns 单位)。"""
    fake = types.ModuleType("edge_tts")

    class Communicate:
        def __init__(self, text, voice, **kwargs):
            self.kwargs = kwargs

        async def stream(self):
            yield {"type": "audio", "data": b"\x00" * 32}
            yield {"type": "WordBoundary", "text": "你好", "offset": 0, "duration": 50_000_000}
            yield {"type": "audio", "data": b"\x01" * 32}

    fake.Communicate = Communicate  # type: ignore[attr-defined]
    sys.modules["edge_tts"] = fake


@pytest.mark.asyncio
async def test_edge_tts_word_boundary_contract(tmp_path: Path) -> None:
    _install_fake_edge_tts()
    try:
        out = tmp_path / "seg.mp3"
        result = await edge_tts_word_boundary("你好", "zh-CN-XiaoxiaoNeural", output_path=out)
        # audio 落盘 + 词级时间戳换算为秒(100ns → s)
        assert result["audio_path"] == out
        assert out.exists() and out.stat().st_size == 64
        assert result["words"] == [{"text": "你好", "start": 0.0, "end": 5.0}]
    finally:
        del sys.modules["edge_tts"]


@pytest.mark.asyncio
async def test_edge_tts_word_boundary_passes_rate_pitch(tmp_path: Path) -> None:
    captured: dict = {}

    class Communicate:
        def __init__(self, text, voice, **kwargs):
            captured.update(kwargs)

        async def stream(self):
            yield {"type": "audio", "data": b"\x00" * 16}

    fake = types.ModuleType("edge_tts")
    fake.Communicate = Communicate  # type: ignore[attr-defined]
    sys.modules["edge_tts"] = fake
    try:
        await edge_tts_word_boundary(
            "hi", "en-US-JennyNeural", rate="-10%", pitch="+2Hz", output_path=tmp_path / "a.mp3"
        )
        assert captured == {"boundary": "WordBoundary", "rate": "-10%", "pitch": "+2Hz"}
    finally:
        del sys.modules["edge_tts"]


@pytest.mark.asyncio
async def test_edge_tts_word_boundary_no_audio_raises(tmp_path: Path) -> None:
    class Communicate:
        def __init__(self, text, voice, **kwargs):
            pass

        async def stream(self):
            yield {"type": "WordBoundary", "text": "x", "offset": 0, "duration": 1}

    fake = types.ModuleType("edge_tts")
    fake.Communicate = Communicate  # type: ignore[attr-defined]
    sys.modules["edge_tts"] = fake
    try:
        with pytest.raises(EdgeTtsWordBoundaryError):
            await edge_tts_word_boundary("x", "v", output_path=tmp_path / "b.mp3")
    finally:
        del sys.modules["edge_tts"]


def test_probe_duration_real_ffmpeg(tmp_path: Path) -> None:
    import subprocess

    wav = tmp_path / "tone.wav"
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
            "sine=frequency=440:duration=1.5", "-ar", "8000", "-ac", "1", str(wav),
        ],
        check=True,
        capture_output=True,
    )
    assert abs(probe_duration(wav) - 1.5) < 0.1


def test_probe_duration_missing_file_raises(tmp_path: Path) -> None:
    from oprim._probe_duration import ProbeDurationError

    with pytest.raises(ProbeDurationError):
        probe_duration(tmp_path / "nope.wav")
