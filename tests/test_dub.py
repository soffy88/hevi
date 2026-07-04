"""翻译配音导出测试(§3 L2)。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from hevi.assembly.subtitle_align import Cue
from hevi.dub import dub_video, translate_cues


@pytest.mark.asyncio
async def test_translate_cues_translates_and_keeps_timing():
    cues = [Cue(start=0.0, end=1.0, text="你好"), Cue(start=1.0, end=2.0, text="再见")]
    llm = AsyncMock(return_value={"content": '{"0":"hello","1":"goodbye"}'})
    out = await translate_cues(cues, target_language="en", llm=llm)
    assert [c.text for c in out] == ["hello", "goodbye"]
    assert out[0].start == 0.0 and out[1].end == 2.0  # 时间码不变


@pytest.mark.asyncio
async def test_translate_cues_fallback_keeps_source():
    cues = [Cue(start=0.0, end=1.0, text="原文")]
    llm = AsyncMock(side_effect=RuntimeError("down"))
    out = await translate_cues(cues, target_language="en", llm=llm)
    assert out[0].text == "原文"  # 兜底原文


@pytest.mark.asyncio
async def test_dub_video_orchestration():
    """ASR → 翻译 → synth → mux 编排(注入 mock 各步)。"""
    cues = [Cue(start=0.0, end=1.0, text="你好世界")]
    calls = {}

    def transcribe_fn(p):
        calls["transcribed"] = str(p)
        return cues

    async def synth_fn(*, cues, language, output_path):
        calls["synth"] = (len(cues), language)
        return output_path

    async def mux_fn(*, video, audio, output):
        calls["mux"] = str(output)
        return output

    llm = AsyncMock(return_value={"content": '{"0":"hello world"}'})
    res = await dub_video(
        video_path="in.mp4", target_language="en", output_path="out_en.mp4",
        llm=llm, transcribe_fn=transcribe_fn, synth_fn=synth_fn, mux_fn=mux_fn,
    )
    assert res == {"output": "out_en.mp4", "language": "en", "cues": 1}
    assert calls["transcribed"] == "in.mp4"
    assert calls["synth"] == (1, "en")  # 翻译后的 cue 交给 synth
    assert calls["mux"] == "out_en.mp4"
