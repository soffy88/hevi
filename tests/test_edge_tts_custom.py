"""hevi.audio.edge_tts_custom 测试 —— edge_tts 语速/音高/音色覆盖(hevi 自有实现,不改 vendored oprim)。

edge_tts 包本身走 mock(不实际联网合成);验证的是参数拼装 + 音色解析 + ffmpeg concat 调用。
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from hevi.audio.edge_tts_custom import CURATED_VOICES, synthesize_with_voice_control


def _install_fake_edge_tts(calls: list[dict]) -> None:
    """edge_tts 是可选依赖,测试环境未必装了;造一个假的顶级模块供 import 使用。"""
    fake = types.ModuleType("edge_tts")

    class Communicate:
        def __init__(self, text: str, voice: str, rate: str = "+0%", pitch: str = "+0Hz"):
            calls.append({"text": text, "voice": voice, "rate": rate, "pitch": pitch})

        async def save(self, path: str) -> None:
            Path(path).write_bytes(b"\x00" * 64)

    fake.Communicate = Communicate  # type: ignore[attr-defined]
    sys.modules["edge_tts"] = fake


@pytest.mark.asyncio
async def test_synthesize_single_line_with_rate_pitch(tmp_path: Path) -> None:
    calls: list[dict] = []
    _install_fake_edge_tts(calls)
    try:
        out = tmp_path / "out.wav"
        with patch("hevi.audio.edge_tts_custom.ffmpeg_run", new_callable=AsyncMock) as mrun:
            mrun.side_effect = lambda **kw: out.write_bytes(b"\x00" * 32)
            await synthesize_with_voice_control(
                config={"language": "zh"},
                script=[SimpleNamespace(text="你好")],
                output_path=out,
                rate="+15%",
                pitch="+2Hz",
            )
        assert calls[0]["rate"] == "+15%"
        assert calls[0]["pitch"] == "+2Hz"
        assert calls[0]["voice"] == CURATED_VOICES["zh_female_standard"]  # 自动按语言选音色
    finally:
        del sys.modules["edge_tts"]


@pytest.mark.asyncio
async def test_synthesize_explicit_curated_voice_overrides_auto(tmp_path: Path) -> None:
    calls: list[dict] = []
    _install_fake_edge_tts(calls)
    try:
        out = tmp_path / "out.wav"
        with patch("hevi.audio.edge_tts_custom.ffmpeg_run", new_callable=AsyncMock) as mrun:
            mrun.side_effect = lambda **kw: out.write_bytes(b"\x00" * 32)
            await synthesize_with_voice_control(
                config={"language": "zh"},
                script=[SimpleNamespace(text="你好")],
                output_path=out,
                voice="zh_male_deep",
            )
        assert calls[0]["voice"] == CURATED_VOICES["zh_male_deep"]
    finally:
        del sys.modules["edge_tts"]


@pytest.mark.asyncio
async def test_synthesize_raw_edge_tts_voice_id_passthrough(tmp_path: Path) -> None:
    """voice 不在 CURATED_VOICES 里 → 当作原生 edge-tts 音色 ID 直传。"""
    calls: list[dict] = []
    _install_fake_edge_tts(calls)
    try:
        out = tmp_path / "out.wav"
        with patch("hevi.audio.edge_tts_custom.ffmpeg_run", new_callable=AsyncMock) as mrun:
            mrun.side_effect = lambda **kw: out.write_bytes(b"\x00" * 32)
            await synthesize_with_voice_control(
                script=[SimpleNamespace(text="hi")],
                output_path=out,
                voice="en-US-JennyNeural",
            )
        assert calls[0]["voice"] == "en-US-JennyNeural"
    finally:
        del sys.modules["edge_tts"]


@pytest.mark.asyncio
async def test_synthesize_empty_script_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        await synthesize_with_voice_control(script=[], output_path=tmp_path / "out.wav")
