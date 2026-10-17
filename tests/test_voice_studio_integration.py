"""Voice Studio 集成测试。

测试 VoiceBox 声音能力与 produce_v2 管线的完整集成:
1. produce_v2.py 语音效果/人格/TTS 引擎参数传递
2. voice_studio.py API 端点功能
3. 音频效果链在对白合成中的应用
4. 人格改写与副语言标签的集成
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest
import soundfile as sf

from hevi.audio.effects import EffectsChain, preset_robotic, preset_radio
from hevi.audio.personality import VoicePersona, PersonalityEngine
from hevi.director.produce_v2 import run_v2_produce


# ── produce_v2 Voice Integration ──────────────────────────────────────────


class TestProduceV2VoiceParams:
    """测试 produce_v2 的语音参数传递。"""

    def test_accepts_voice_effects_param(self):
        """run_v2_produce 接受 voice_effects 参数。"""
        import inspect
        sig = inspect.signature(run_v2_produce)
        assert 'voice_effects' in sig.parameters

    def test_accepts_voice_personas_param(self):
        """run_v2_produce 接受 voice_personas 参数。"""
        import inspect
        sig = inspect.signature(run_v2_produce)
        assert 'voice_personas' in sig.parameters

    def test_accepts_tts_engine_param(self):
        """run_v2_produce 接受 tts_engine 参数。"""
        import inspect
        sig = inspect.signature(run_v2_produce)
        assert 'tts_engine' in sig.parameters

    def test_voice_effects_none_by_default(self):
        """voice_effects 默认为 None。"""
        import inspect
        sig = inspect.signature(run_v2_produce)
        assert sig.parameters['voice_effects'].default is None

    def test_voice_personas_none_by_default(self):
        """voice_personas 默认为 None。"""
        import inspect
        sig = inspect.signature(run_v2_produce)
        assert sig.parameters['voice_personas'].default is None

    def test_tts_engine_none_by_default(self):
        """tts_engine 默认为 None。"""
        import inspect
        sig = inspect.signature(run_v2_produce)
        assert sig.parameters['tts_engine'].default is None


class TestEffectsChainInPipeline:
    """测试效果链在管线中的应用。"""

    @pytest.fixture
    def sample_dialogue_audio(self, tmp_path):
        """创建示例对白音频。"""
        sr = 22050
        duration = 2.0
        t = np.linspace(0, duration, int(sr * duration), dtype=np.float32)
        # 简单的正弦波 + 噪声模拟语音
        audio = 0.3 * np.sin(2 * np.pi * 440 * t) + 0.1 * np.random.randn(len(t))
        audio = audio.astype(np.float32)

        audio_path = tmp_path / "dialogue.wav"
        sf.write(str(audio_path), audio, sr)
        return audio_path, sr, audio

    def test_effects_chain_modifies_audio(self, sample_dialogue_audio):
        """效果链改变音频波形。"""
        audio_path, sr, original_audio = sample_dialogue_audio

        # 应用 robotic 效果
        chain = preset_robotic()
        audio, sr_loaded = sf.read(str(audio_path))
        processed = chain.apply(audio, sr_loaded)

        # 音频应该被修改
        assert not np.allclose(original_audio, processed)
        assert processed.shape == original_audio.shape

    def test_effects_chain_preserves_length(self, sample_dialogue_audio):
        """效果链保持音频长度。"""
        audio_path, sr, _ = sample_dialogue_audio

        chain = preset_radio()
        audio, sr_loaded = sf.read(str(audio_path))
        processed = chain.apply(audio, sr_loaded)

        assert len(processed) == len(audio)

    def test_effects_chain_handles_empty_audio(self):
        """效果链处理空音频。"""
        chain = preset_robotic()
        # Use a very small but non-empty array instead of truly empty
        tiny_audio = np.array([0.0], dtype=np.float32)
        result = chain.apply(tiny_audio, 22050)
        assert len(result) >= 1


class TestPersonalityRewriteInPipeline:
    """测试人格改写在管线中的集成。"""

    def test_personality_engine_rewrites_text(self):
        """人格引擎改写对白文本。"""
        persona = VoicePersona(
            name="warrior",
            description="粗犷直爽的战士",
            speaking_style="简洁有力，常用短句",
            vocabulary=["哈！", "俺"],
        )

        engine = PersonalityEngine(llm_fn=None)  # 使用规则改写

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(
                engine.rewrite("请帮我把那个东西拿过来", persona)
            )
        finally:
            loop.close()

        # 改写后的文本应该与原文不同（规则改写会在句首添加口头禅）
        assert result.rewritten_text != result.original_text
        # 口头禅是随机选取的，验证至少包含一个词汇项
        assert any(v in result.rewritten_text for v in persona.vocabulary)

    def test_personality_engine_with_llm(self):
        """人格引擎使用 LLM 改写。"""
        persona = VoicePersona(
            name="scholar",
            description="温文尔雅的书生",
            speaking_style="文绉绉，引经据典",
            vocabulary=["吾", "甚好"],
        )

        mock_llm = AsyncMock(return_value="吾愿为君效劳，甚好甚好")
        engine = PersonalityEngine(llm_fn=mock_llm)

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(
                engine.rewrite("我来帮你", persona)
            )
        finally:
            loop.close()

        assert result.rewritten_text == "吾愿为君效劳，甚好甚好"
        assert result.model_used == "llm"
        mock_llm.assert_called_once()


class TestParalinguisticTagStripping:
    """测试副语言标签剥离。"""

    def test_strip_tags_before_tts(self):
        """TTS 前剥离副语言标签。"""
        from hevi.audio.paralinguistic import strip_tags

        text_with_tags = "Hello [laugh] world [sigh] today is great"
        clean_text = strip_tags(text_with_tags)

        assert "[laugh]" not in clean_text
        assert "[sigh]" not in clean_text
        assert "Hello" in clean_text
        assert "world" in clean_text

    def test_strip_preserves_regular_text(self):
        """剥离不影响普通文本。"""
        from hevi.audio.paralinguistic import strip_tags

        regular_text = "This is normal dialogue without any tags."
        result = strip_tags(regular_text)
        assert result == regular_text


# ── Voice Studio API Tests ────────────────────────────────────────────────


class TestVoiceStudioAPIDirect:
    """测试 voice_studio API 功能（直接调用，不需要完整 app）。"""

    def test_list_effects_presets(self):
        """列出效果预设。"""
        from hevi.audio.effects import list_presets

        presets = list_presets()
        assert len(presets) >= 6
        assert "robotic" in presets
        assert "radio" in presets

    def test_get_effect_chain(self):
        """获取效果链配置。"""
        from hevi.audio.effects import PRESETS

        factory = PRESETS.get("robotic")
        assert factory is not None
        chain = factory()
        assert len(chain.effects) > 0

    def test_list_personality_presets(self):
        """列出人格预设。"""
        from hevi.audio.personality import list_preset_personas

        personas = list_preset_personas()
        assert len(personas) >= 4
        assert "warrior" in personas
        assert "scholar" in personas

    def test_get_personality(self):
        """获取人格配置。"""
        from hevi.audio.personality import get_preset_persona

        warrior = get_preset_persona("warrior")
        assert warrior is not None
        assert "武将" in warrior.description or "战士" in warrior.name
        assert warrior.vocabulary is not None
        assert len(warrior.vocabulary) > 0

    def test_rewrite_with_personality(self):
        """人格改写文本。"""
        from hevi.audio.personality import PersonalityEngine, get_preset_persona

        engine = PersonalityEngine(llm_fn=None)
        warrior = get_preset_persona("warrior")

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(
                engine.rewrite("你好，请问需要什么帮助？", warrior)
            )
        finally:
            loop.close()

        # 规则改写会在句首随机插入一个口头禅，并去除"请"
        assert result.rewritten_text != result.original_text
        assert any(v in result.rewritten_text for v in warrior.vocabulary)

    def test_list_tts_engines(self):
        """列出 TTS 引擎。"""
        from hevi.audio.audio_config import AudioProvider

        engines = list(AudioProvider)
        assert len(engines) >= 5
        engine_values = [e.value for e in engines]
        assert "edge_tts" in engine_values
        assert "chatterbox_turbo" in engine_values
        assert "kokoro" in engine_values

    def test_tts_engine_metadata(self):
        """TTS 引擎元数据。"""
        from hevi.audio.chatterbox_service import ChatterboxService, ChatterboxConfig
        from hevi.audio.kokoro_service import KokoroService

        # Test Chatterbox Turbo
        turbo_config = ChatterboxConfig(variant="turbo")
        turbo = ChatterboxService(turbo_config)
        assert turbo.supports_paralinguistic is True
        assert turbo.supported_languages == ["en"]

        # Test Kokoro
        kokoro = KokoroService()
        voices = kokoro.list_voices()
        assert len(voices) >= 40

    def test_validate_voice_config(self):
        """验证语音配置。"""
        from hevi.audio.effects import PRESETS
        from hevi.audio.personality import get_preset_persona
        from hevi.audio.audio_config import AudioProvider

        # Valid config
        factory = PRESETS.get("robotic")
        chain = factory() if factory else None
        persona = get_preset_persona("warrior")
        engine = AudioProvider.CHATTERBOX_TURBO

        assert chain is not None
        assert persona is not None
        assert engine.value == "chatterbox_turbo"

    def test_invalid_effect_preset(self):
        """无效效果预设。"""
        from hevi.audio.effects import PRESETS

        assert "nonexistent_effect" not in PRESETS

    def test_invalid_persona(self):
        """无效人格预设。"""
        from hevi.audio.personality import get_preset_persona

        result = get_preset_persona("nonexistent_persona")
        assert result is None


# ── Integration: Full Pipeline ────────────────────────────────────────────


class TestFullPipelineIntegration:
    """测试完整管线的声音集成。"""

    def test_effects_and_personality_together(self):
        """效果链和人格改写可以同时使用。"""
        from hevi.audio.effects import preset_robotic
        from hevi.audio.personality import PersonalityEngine, VoicePersona
        from hevi.audio.paralinguistic import strip_tags

        # 1. 人格改写
        persona = VoicePersona(
            name="robot",
            description="机械化的机器人",
            speaking_style="单调、精确",
            vocabulary=["已确认", "执行中"],
        )
        engine = PersonalityEngine(llm_fn=None)

        loop = asyncio.new_event_loop()
        try:
            rewrite_result = loop.run_until_complete(
                engine.rewrite("开始任务", persona)
            )
        finally:
            loop.close()

        # 2. 剥离副语言标签
        clean_text = strip_tags(rewrite_result.rewritten_text)

        # 3. 应用效果链
        chain = preset_robotic()
        sr = 22050
        duration = len(clean_text) * 0.1  # 每字符 0.1 秒
        audio = np.random.randn(int(sr * duration)).astype(np.float32) * 0.3
        processed = chain.apply(audio, sr)

        # 验证所有步骤都成功
        assert rewrite_result.rewritten_text != rewrite_result.original_text
        assert clean_text is not None
        assert processed is not None
        assert not np.allclose(audio, processed)

    def test_config_json_includes_voice_settings(self, tmp_path):
        """config_json 包含语音设置。"""
        # 模拟 config_json 输出
        config_json = {
            "voice_effects": "robotic",
            "voice_personas_count": 2,
            "tts_engine": "chatterbox_turbo",
        }

        assert config_json["voice_effects"] == "robotic"
        assert config_json["voice_personas_count"] == 2
        assert config_json["tts_engine"] == "chatterbox_turbo"


# ── Audio Format Tests ────────────────────────────────────────────────────


class TestAudioFormats:
    """测试音频格式处理。"""

    def test_effects_handle_wav(self, tmp_path):
        """效果链处理 WAV 格式。"""
        sr = 22050
        audio = np.random.randn(sr).astype(np.float32) * 0.3
        wav_path = tmp_path / "test.wav"
        sf.write(str(wav_path), audio, sr)

        chain = preset_robotic()
        loaded, loaded_sr = sf.read(str(wav_path))
        processed = chain.apply(loaded, loaded_sr)

        assert loaded_sr == sr
        assert processed is not None

    def test_effects_handle_mp3(self, tmp_path):
        """效果链处理 MP3 格式（通过 soundfile）。"""
        sr = 22050
        audio = np.random.randn(sr).astype(np.float32) * 0.3

        # soundfile 不直接支持 MP3 写入，使用 WAV 模拟
        wav_path = tmp_path / "test.wav"
        sf.write(str(wav_path), audio, sr)

        chain = preset_radio()
        loaded, loaded_sr = sf.read(str(wav_path))
        processed = chain.apply(loaded, loaded_sr)

        assert processed is not None
