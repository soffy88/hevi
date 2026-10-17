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


@pytest.mark.asyncio
async def test_edge_tts_default_voice_is_resolved_to_native_neural_voice(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("HEVI_EXPLAINER_TTS_PROVIDER", "edge_tts")
    seen: dict[str, str] = {}

    async def fake_edge(text: str, *, voice: str, rate: str, output_path: Path):
        seen["voice"] = voice
        output_path.write_bytes(b"fake mp3")
        return {
            "words": [
                {"text": "第一句", "start": 0.0, "end": 0.8},
                {"text": "第二句", "start": 0.9, "end": 1.8},
            ]
        }

    monkeypatch.setattr("hevi.explainer.voiceover.edge_tts_word_boundary", fake_edge)
    monkeypatch.setattr("hevi.explainer.voiceover.probe_duration", lambda _path: 2.0)

    manifest = await synthesize_storyboard(_storyboard(), tmp_path)

    assert seen["voice"] == "zh-CN-XiaoxiaoNeural"
    assert manifest[0].audio_file == "audio/hook.mp3"


@pytest.mark.asyncio
async def test_edge_tts_preserves_explicit_native_voice(monkeypatch, tmp_path: Path):
    seen: dict[str, str] = {}

    async def fake_edge(text: str, *, voice: str, rate: str, output_path: Path):
        seen["voice"] = voice
        output_path.write_bytes(b"fake mp3")
        return {"words": [{"text": text, "start": 0.0, "end": 1.0}]}

    monkeypatch.setattr("hevi.explainer.voiceover.edge_tts_word_boundary", fake_edge)
    monkeypatch.setattr("hevi.explainer.voiceover.probe_duration", lambda _path: 1.0)

    await synthesize_storyboard(
        _storyboard(),
        tmp_path,
        provider="edge_tts",
        voice="en-US-AriaNeural",
    )

    assert seen["voice"] == "en-US-AriaNeural"


def test_story_film_tts_defaults_to_lux_tts(monkeypatch):
    from hevi.explainer.voiceover import _provider

    monkeypatch.delenv("HEVI_EXPLAINER_TTS_PROVIDER", raising=False)
    monkeypatch.delenv("HEVI_TTS_FORMAL_PROVIDER", raising=False)
    assert _provider() == "lux_tts"


@pytest.mark.asyncio
async def test_story_film_lux_tts_uses_shared_router_and_keeps_wav_manifest(
    monkeypatch, tmp_path: Path
):
    monkeypatch.delenv("HEVI_EXPLAINER_TTS_PROVIDER", raising=False)
    monkeypatch.delenv("HEVI_TTS_FORMAL_PROVIDER", raising=False)
    seen: dict[str, object] = {}

    async def fake_formal(*, text, output_path, voice, instruct, **_kwargs):
        seen.update(
            text=text,
            output_path=output_path,
            voice=voice,
            instruct=instruct,
        )
        output_path.write_bytes(b"RIFF fake wav")
        return {
            "path": output_path,
            "requested_provider": "lux_tts",
            "actual_provider": "lux_tts",
            "substituted": False,
        }

    monkeypatch.setattr("hevi.audio.audio_router._synthesize_formal", fake_formal)
    monkeypatch.setattr("hevi.explainer.voiceover.probe_duration", lambda _path: 3.25)

    manifest = await synthesize_storyboard(_storyboard(), tmp_path)

    assert seen["text"] == "第一句。第二句。"
    assert seen["output_path"] == tmp_path / "hook.wav"
    assert "2-6" in str(seen["instruct"])
    assert manifest[0].audio_file == "audio/hook.wav"
    assert manifest[0].duration_sec == 3.25
    assert manifest[0].captions[-1].end == 3.25
    assert (tmp_path / "hook.wav").is_file()


@pytest.mark.asyncio
async def test_digital_human_dialogue_defaults_to_shared_lux_tts_router(
    monkeypatch, tmp_path: Path
):
    from hevi.digital_human import line_tts

    monkeypatch.delenv("HEVI_TTS_FORMAL_PROVIDER", raising=False)
    monkeypatch.delenv("HEVI_EXPLAINER_TTS_PROVIDER", raising=False)
    assert line_tts._provider() == "lux_tts"
    seen: dict[str, object] = {}

    async def fake_formal(*, text, output_path, voice, instruct, **_kwargs):
        seen.update(text=text, voice=voice, instruct=instruct)
        output_path.write_bytes(b"RIFF fake wav")
        return {
            "path": output_path,
            "requested_provider": "lux_tts",
            "actual_provider": "lux_tts",
            "substituted": False,
        }

    monkeypatch.setattr("hevi.audio.audio_router._synthesize_formal", fake_formal)
    target = tmp_path / "dialogue.wav"
    result = await line_tts.synthesize_line("你好，小兔子。", target)

    assert result == target
    assert target.is_file()
    assert seen["text"] == "你好，小兔子。"
    assert "2-6" in str(seen["instruct"])
