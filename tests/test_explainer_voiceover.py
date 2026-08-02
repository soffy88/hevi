from __future__ import annotations

from pathlib import Path

import pytest

from hevi.explainer.schemas import Storyboard
from hevi.explainer.voiceover import VoiceoverError, synthesize_storyboard


def _storyboard() -> Storyboard:
    return Storyboard(
        topic="测试",
        segments=[
            {
                "id": "hook",
                "sceneType": "hook",
                "narration": "第一句。第二句。",
                "props": {
                    "title": "测试",
                    "subtitle": "说明",
                    "items": [{"emoji": "💡", "label": "要点"}],
                },
            }
        ],
    )


@pytest.mark.asyncio
async def test_voicebox_audio_uses_wav_and_duration_captions(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("HEVI_EXPLAINER_TTS_PROVIDER", "voicebox")

    async def fake_voicebox(_text: str, output_path: Path, **_kwargs):
        output_path.write_bytes(b"RIFF fake wav")

    monkeypatch.setattr("hevi.explainer.voiceover.synthesize_voicebox", fake_voicebox)
    # 3O §2 Task 2.2:时长探测已收敛到 oprim.probe_duration(经模块级 import 绑定),
    # 故在 voiceover 模块命名空间打桩。
    monkeypatch.setattr("hevi.explainer.voiceover.probe_duration", lambda _path: 4.0)

    manifest = await synthesize_storyboard(_storyboard(), tmp_path)

    assert manifest[0].audio_file == "audio/hook.wav"
    assert [cue.text for cue in manifest[0].captions] == ["第一句", "第二句"]
    assert manifest[0].captions[-1].end == 4.0


@pytest.mark.asyncio
async def test_voicebox_failure_is_not_silently_replaced(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("HEVI_EXPLAINER_TTS_PROVIDER", "voicebox")
    monkeypatch.delenv("VOICEBOX_ALLOW_EDGE_FALLBACK", raising=False)

    async def fail_voicebox(*_args, **_kwargs):
        from hevi.explainer.voicebox_client import VoiceboxError

        raise VoiceboxError("sidecar down")

    monkeypatch.setattr("hevi.explainer.voiceover.synthesize_voicebox", fail_voicebox)

    with pytest.raises(VoiceoverError, match="Voicebox 配音失败: sidecar down"):
        await synthesize_storyboard(_storyboard(), tmp_path)
