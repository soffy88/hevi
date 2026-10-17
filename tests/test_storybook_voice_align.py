"""Unit tests for storybook voice alignment (配音对齐、双语字幕、角色音色、BGM 避让留白、豆包 Provider 接口)."""

from __future__ import annotations

import wave
from pathlib import Path

import pytest

from hevi.audio.providers.doubao_tts import DoubaoKeyMissingError, DoubaoStorybookTTSProvider
from hevi.audio.storybook_voice import (
    VoiceLine,
    align_and_retime_storybook,
    export_bilingual_subtitles_srt,
    mix_storybook_audio_master,
    synthesize_local_speech,
)
from hevi.capabilities import get, names, resolve


def test_storybook_voice_align_registered():
    assert "storybook.voice_align" in names()
    cap = get("storybook.voice_align")
    assert cap.name == "storybook.voice_align"
    assert cap.kind == "audio"
    assert "16:9" in cap.aspects


def test_doubao_provider_skips_when_no_key(monkeypatch):
    """验证豆包仅做可选 provider 接口，无 key 时跳过，严禁发起付费网络请求。"""
    monkeypatch.delenv("DOUBAO_APPID", raising=False)
    monkeypatch.delenv("DOUBAO_ACCESS_TOKEN", raising=False)

    provider = DoubaoStorybookTTSProvider()
    assert provider.is_available() is False

    with pytest.raises(DoubaoKeyMissingError) as exc_info:
        provider.synthesize("测试台词", Path("/tmp/dummy.wav"))
    assert "skipping" in str(exc_info.value).lower()


def test_synthesize_local_speech_multi_roles(tmp_path: Path):
    """验证多角色音色与语气真实本地合成（旁白、小狐狸、小熊、花）。"""
    roles = ["narrator", "fox", "bear", "flower"]
    durations = {}

    for r in roles:
        out_wav = tmp_path / f"role_{r}.wav"
        dur = synthesize_local_speech("森林里的清晨好美丽！", r, out_wav)
        assert out_wav.is_file()
        assert out_wav.stat().st_size > 500
        assert dur > 0.3

        with wave.open(str(out_wav), "rb") as wf:
            assert wf.getframerate() == 48000
            assert wf.getnchannels() == 1
            durations[r] = dur

    # 小狐狸语速较快(length_scale 0.92)，小熊语速较慢(length_scale 1.30)
    assert durations["fox"] < durations["bear"]


def test_align_and_retime_with_bilingual_subtitles(tmp_path: Path):
    """验证按 TTS 实际时长重排镜头与双语字幕对齐（误差严格 < 150ms）。"""
    lines = [
        VoiceLine("L1", "narrator", "清晨的阳光洒在树叶上。", "Morning sunlight shines upon the leaves.", "shot_1"),
        VoiceLine("L2", "fox", "哇！是一颗闪闪发光的小种子！", "Wow! A tiny glowing seed!", "shot_2", is_quiet_break=True),
        VoiceLine("L3", "bear", "我们一起为它浇水吧。", "Let us water it together.", "shot_3"),
    ]

    cues, retimed_shots, _total_dur = align_and_retime_storybook(
        lines,
        tmp_path / "align_test",
        quiet_break_s=2.0,
    )

    assert len(cues) == 3
    # 包含了 shot_1, shot_2, quiet_break_2, shot_3 共有 4 段镜头/区间
    assert len(retimed_shots) == 4
    assert any(s["shot_id"].startswith("quiet_break") for s in retimed_shots)

    # 验证字幕对齐精度：字幕时长与实测音频时长完全一致 (drift < 10ms)
    for c in cues:
        cue_dur = c.end_ms - c.start_ms
        drift = abs(cue_dur - c.audio_duration_ms)
        assert drift < 15, f"Cue {c.cue_id} alignment drift {drift}ms exceeds 150ms"

    # 验证中英双语字幕 SRT 导出格式
    srt_path = tmp_path / "subtitles.srt"
    export_bilingual_subtitles_srt(cues, srt_path)
    srt_text = srt_path.read_text(encoding="utf-8")

    assert "清晨的阳光洒在树叶上。" in srt_text
    assert "Morning sunlight shines upon the leaves." in srt_text
    assert "00:00:" in srt_text
    assert "-->" in srt_text


def test_mix_audio_master_with_ducking_and_quiet_segment(tmp_path: Path):
    """验证 BGM 自动避让与安静留白段。"""
    lines = [
        VoiceLine("L1", "narrator", "小种子轻轻发芽了。", "The little seed sprouted gently.", "shot_1", is_quiet_break=True),
        VoiceLine("L2", "fox", "长成一朵小花了！", "It grew into a little flower!", "shot_2"),
    ]

    cues, _, total_dur = align_and_retime_storybook(lines, tmp_path / "mix_test", quiet_break_s=2.5)

    master_wav, voice_wav = mix_storybook_audio_master(
        cues,
        total_dur,
        tmp_path / "mix_test" / "master.wav",
        bgm_mood="calm",
        seed=101,
    )

    assert master_wav.is_file()
    assert voice_wav.is_file()

    with wave.open(str(master_wav), "rb") as wf:
        assert wf.getnchannels() == 2  # 立体声
        assert wf.getframerate() == 48000
        frames = wf.getnframes()
        actual_dur = frames / 48000.0
        assert abs(actual_dur - total_dur) < 0.1


def test_storybook_voice_align_capability_render(tmp_path: Path):
    """验证 storybook.voice_align capability 完整端到端渲染。"""
    cap = resolve("storybook.voice_align")
    out_dir = tmp_path / "voice_cap_out"

    script = [
        {"line_id": "L1", "role": "narrator", "text_zh": "第一缕晨光醒来了。", "text_en": "The first morning light awakened.", "shot_id": "S1"},
        {"line_id": "L2", "role": "fox", "text_zh": "我们出发吧！", "text_en": "Let's go!", "shot_id": "S2", "is_quiet_break": True},
    ]

    res = cap.render(
        {"script": script, "quiet_break_s": 1.5, "bgm_style": "calm"},
        out_dir,
        aspect="16:9",
        seed=42,
    )

    assert res.wav is not None
    assert Path(res.wav).is_file()
    assert (out_dir / "bilingual_subtitles.srt").is_file()
    assert (out_dir / "alignment.json").is_file()
    assert res.duration_s > 2.0
    assert res.qa["max_alignment_error_ms"] < 150.0
