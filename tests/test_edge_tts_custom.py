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

from hevi.audio.edge_tts_custom import (
    CURATED_VOICES,
    edge_tts_synthesize_smart,
    emotion_to_rate_pitch,
    synthesize_with_voice_control,
)


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


# ── emotion_to_rate_pitch(2026-07-13,治"ScriptLine.emotion 填了但 TTS 从不读")────


class TestEmotionToRatePitch:
    def test_no_emotion_is_neutral(self) -> None:
        assert emotion_to_rate_pitch(None) == ("+0%", "+0Hz")
        assert emotion_to_rate_pitch("") == ("+0%", "+0Hz")

    def test_unknown_emotion_falls_back_neutral(self) -> None:
        assert emotion_to_rate_pitch("莫名其妙的心情") == ("+0%", "+0Hz")

    def test_sad_slows_down_and_lowers_pitch(self) -> None:
        rate, pitch = emotion_to_rate_pitch("悲怆")
        assert rate == "-15%"
        assert pitch == "-15Hz"

    def test_fear_speeds_up(self) -> None:
        rate, _pitch = emotion_to_rate_pitch("惊惧")
        assert rate == "+20%"

    def test_multi_keyword_label_matches_first_bucket(self) -> None:
        """ "倨傲/决绝"(LLM 常见的多关键词标签格式)命中"怒/愤/...倨傲"桶。"""
        rate, pitch = emotion_to_rate_pitch("倨傲/决绝")
        assert (rate, pitch) == ("-5%", "-10Hz")


@pytest.mark.asyncio
async def test_voice_control_derives_rate_pitch_from_emotion(tmp_path: Path) -> None:
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
                emotion="悲怆",
            )
        assert calls[0]["rate"] == "-15%"
        assert calls[0]["pitch"] == "-15Hz"
    finally:
        del sys.modules["edge_tts"]


@pytest.mark.asyncio
async def test_voice_control_explicit_rate_pitch_overrides_emotion(tmp_path: Path) -> None:
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
                emotion="悲怆",
            )
        assert calls[0]["rate"] == "+15%"
        assert calls[0]["pitch"] == "+2Hz"
    finally:
        del sys.modules["edge_tts"]


# ── edge_tts_synthesize_smart(2026-07-13,"edge_tts" provider 注册的真实入口)─────


@pytest.mark.asyncio
async def test_smart_routes_to_voice_control_when_voice_given(tmp_path: Path) -> None:
    """provider 收到显式 voice → 真的换音色(治多角色对话只有一个默认声音)。"""
    out = tmp_path / "out.wav"
    with patch(
        "hevi.audio.edge_tts_custom.synthesize_with_voice_control",
        new_callable=AsyncMock,
    ) as mvc:
        mvc.return_value = out
        await edge_tts_synthesize_smart(
            script=[SimpleNamespace(text="你好")], output_path=out, voice="zh_male_deep"
        )
    mvc.assert_awaited_once()
    assert mvc.await_args.kwargs["voice"] == "zh_male_deep"


@pytest.mark.asyncio
async def test_smart_routes_to_voice_control_when_emotion_given_without_voice(
    tmp_path: Path,
) -> None:
    """2026-07-13:没传 voice 但传了 emotion(旁白/未指定音色的对白也要按情绪调语气)
    → 一样走 synthesize_with_voice_control,不需要先有显式音色才能情绪化配音。"""
    out = tmp_path / "out.wav"
    with patch(
        "hevi.audio.edge_tts_custom.synthesize_with_voice_control",
        new_callable=AsyncMock,
    ) as mvc:
        mvc.return_value = out
        await edge_tts_synthesize_smart(
            script=[SimpleNamespace(text="你好")], output_path=out, emotion="惊惧"
        )
    mvc.assert_awaited_once()
    assert mvc.await_args.kwargs["emotion"] == "惊惧"
    assert mvc.await_args.kwargs["voice"] is None


@pytest.mark.asyncio
async def test_smart_falls_back_to_oprim_when_no_voice_no_emotion(tmp_path: Path) -> None:
    """没传 voice 也没传 emotion(旁白/未分配声音的调用方)→ 原样退回
    oprim.edge_tts_synthesize,行为完全不变——这条 provider 注册对既有调用方零回归。"""
    out = tmp_path / "out.wav"
    fake_oprim = AsyncMock(return_value=out)
    with patch("oprim.edge_tts_synthesize", fake_oprim):
        await edge_tts_synthesize_smart(script=[SimpleNamespace(text="你好")], output_path=out)
    fake_oprim.assert_awaited_once()
