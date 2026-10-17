"""VoiceBox 集成测试 — 声音能力对标 jamiepine/voicebox。

测试覆盖:
1. 音频后处理效果链 (effects.py) — 8 种效果器 + 6 种预设 + 文件 I/O
2. 副语言标签 (paralinguistic.py) — 标签解析 + 音频生成 + 文本清洗
3. 语音人格系统 (personality.py) — 改写/即兴/回复 + 规则 fallback
4. Chatterbox 引擎 (chatterbox_service.py) — 配置 + 语言列表 + fallback
5. Kokoro 引擎 (kokoro_service.py) — 配置 + 音色列表 + fallback
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import numpy as np
import pytest
import soundfile as sf


# ── 1. Effects ──────────────────────────────────────────────────────────────


class TestEffectConfig:
    def test_create(self):
        from hevi.audio.effects import EffectConfig

        cfg = EffectConfig(effect_type="reverb", params={"room_size": 0.7})
        assert cfg.effect_type == "reverb"
        assert cfg.params["room_size"] == 0.7
        assert cfg.enabled is True

    def test_disabled(self):
        from hevi.audio.effects import EffectConfig

        cfg = EffectConfig(effect_type="delay", enabled=False)
        assert cfg.enabled is False


class TestEffectsChain:
    def test_empty_chain(self):
        from hevi.audio.effects import EffectsChain

        chain = EffectsChain()
        audio = np.random.randn(44100).astype(np.float32) * 0.5
        result = chain.apply(audio, 44100)
        np.testing.assert_array_equal(result, audio)

    def test_add_effects(self):
        from hevi.audio.effects import EffectsChain

        chain = EffectsChain()
        chain.add("gain", db=3.0).add("reverb", room_size=0.5)
        assert len(chain.effects) == 2

    def test_chain_with_disabled_effect(self):
        from hevi.audio.effects import EffectsChain, EffectConfig

        chain = EffectsChain()
        chain.effects.append(EffectConfig(effect_type="gain", params={"db": 6.0}, enabled=False))
        audio = np.random.randn(44100).astype(np.float32) * 0.5
        result = chain.apply(audio, 44100)
        np.testing.assert_array_equal(result, audio)

    def test_chain_with_unknown_effect(self):
        from hevi.audio.effects import EffectsChain

        chain = EffectsChain()
        chain.add("nonexistent_effect")
        audio = np.random.randn(44100).astype(np.float32) * 0.5
        result = chain.apply(audio, 44100)
        # Should not crash, just skip unknown effect
        assert result.shape == audio.shape


class TestIndividualEffects:
    @pytest.fixture
    def sample_audio(self):
        sr = 22050
        t = np.linspace(0, 1.0, sr, dtype=np.float32)
        return np.sin(2 * np.pi * 440 * t) * 0.5, sr

    def test_gain_positive(self, sample_audio):
        from hevi.audio.effects import gain_adjust

        audio, sr = sample_audio
        result = gain_adjust(audio, sr, db=6.0)
        assert result.shape == audio.shape
        # +6dB ≈ 2x amplitude
        assert np.max(np.abs(result)) > np.max(np.abs(audio)) * 1.5

    def test_gain_negative(self, sample_audio):
        from hevi.audio.effects import gain_adjust

        audio, sr = sample_audio
        result = gain_adjust(audio, sr, db=-6.0)
        assert np.max(np.abs(result)) < np.max(np.abs(audio))

    def test_gain_zero(self, sample_audio):
        from hevi.audio.effects import gain_adjust

        audio, sr = sample_audio
        result = gain_adjust(audio, sr, db=0.0)
        np.testing.assert_allclose(result, audio, atol=1e-6)

    def test_highpass(self, sample_audio):
        from hevi.audio.effects import highpass_filter

        audio, sr = sample_audio
        result = highpass_filter(audio, sr, cutoff_hz=500.0)
        assert result.shape == audio.shape

    def test_lowpass(self, sample_audio):
        from hevi.audio.effects import lowpass_filter

        audio, sr = sample_audio
        result = lowpass_filter(audio, sr, cutoff_hz=2000.0)
        assert result.shape == audio.shape

    def test_reverb(self, sample_audio):
        from hevi.audio.effects import reverb

        audio, sr = sample_audio
        result = reverb(audio, sr, room_size=0.5, damping=0.5, mix=0.3)
        assert result.shape == audio.shape
        assert np.max(np.abs(result)) <= 1.0

    def test_delay(self, sample_audio):
        from hevi.audio.effects import delay

        audio, sr = sample_audio
        result = delay(audio, sr, delay_ms=100.0, feedback=0.3, mix=0.3)
        assert result.shape == audio.shape
        assert np.max(np.abs(result)) <= 1.0

    def test_chorus(self, sample_audio):
        from hevi.audio.effects import chorus

        audio, sr = sample_audio
        result = chorus(audio, sr, rate_hz=2.0, depth_ms=3.0, mix=0.4)
        assert result.shape == audio.shape

    def test_compressor(self, sample_audio):
        from hevi.audio.effects import compressor

        audio, sr = sample_audio
        result = compressor(audio, sr, threshold_db=-10, ratio=4.0)
        assert result.shape == audio.shape

    def test_pitch_shift_up(self, sample_audio):
        from hevi.audio.effects import pitch_shift

        audio, sr = sample_audio
        result = pitch_shift(audio, sr, semitones=3)
        assert result.shape == audio.shape

    def test_pitch_shift_zero(self, sample_audio):
        from hevi.audio.effects import pitch_shift

        audio, sr = sample_audio
        result = pitch_shift(audio, sr, semitones=0.0)
        np.testing.assert_array_equal(result, audio)

    def test_stereo_support(self):
        from hevi.audio.effects import reverb, delay, highpass_filter

        sr = 22050
        mono = np.random.randn(sr).astype(np.float32) * 0.5
        stereo = np.column_stack([mono, mono * 0.8])

        for fn in [reverb, delay, highpass_filter]:
            result = fn(stereo, sr)
            assert result.ndim == 2
            assert result.shape[1] == 2


class TestPresets:
    def test_list_presets(self):
        from hevi.audio.effects import list_presets

        presets = list_presets()
        assert len(presets) >= 6
        assert "robotic" in presets
        assert "radio" in presets
        assert "cave" in presets

    def test_preset_robotic(self):
        from hevi.audio.effects import preset_robotic

        chain = preset_robotic()
        assert len(chain.effects) >= 2

    def test_preset_radio(self):
        from hevi.audio.effects import preset_radio

        chain = preset_radio()
        assert len(chain.effects) >= 3

    def test_all_presets_apply(self):
        from hevi.audio.effects import PRESETS

        sr = 22050
        audio = np.random.randn(sr).astype(np.float32) * 0.3
        for name, factory in PRESETS.items():
            chain = factory()
            result = chain.apply(audio, sr)
            assert result.shape == audio.shape, f"preset {name} failed"


class TestApplyEffectsFile:
    def test_apply_to_file(self, tmp_path):
        from hevi.audio.effects import apply_effects

        sr = 22050
        audio = np.random.randn(sr).astype(np.float32) * 0.3
        input_path = tmp_path / "input.wav"
        output_path = tmp_path / "output.wav"
        sf.write(str(input_path), audio, sr)

        result = apply_effects(input_path, output_path, preset="echo_chamber")
        assert result == output_path
        assert output_path.exists()

        loaded, loaded_sr = sf.read(str(output_path))
        assert loaded_sr == sr
        assert len(loaded) == len(audio)

    def test_apply_preset_by_name(self, tmp_path):
        from hevi.audio.effects import apply_effects

        sr = 22050
        audio = np.random.randn(sr).astype(np.float32) * 0.3
        input_path = tmp_path / "input.wav"
        output_path = tmp_path / "output.wav"
        sf.write(str(input_path), audio, sr)

        result = apply_effects(input_path, output_path, preset="radio")
        assert output_path.exists()

    def test_unknown_preset_raises(self, tmp_path):
        from hevi.audio.effects import apply_effects

        sr = 22050
        audio = np.random.randn(sr).astype(np.float32) * 0.3
        input_path = tmp_path / "input.wav"
        output_path = tmp_path / "output.wav"
        sf.write(str(input_path), audio, sr)

        with pytest.raises(ValueError, match="unknown preset"):
            apply_effects(input_path, output_path, preset="nonexistent")


class TestApplyEffectsToArray:
    def test_apply_to_array(self):
        from hevi.audio.effects import apply_effects_to_array

        sr = 22050
        audio = np.random.randn(sr).astype(np.float32) * 0.3
        result = apply_effects_to_array(audio, sr, preset="echo_chamber")
        assert result.shape == audio.shape

    def test_no_chain_returns_copy(self):
        from hevi.audio.effects import apply_effects_to_array

        sr = 22050
        audio = np.random.randn(sr).astype(np.float32) * 0.3
        result = apply_effects_to_array(audio, sr)
        np.testing.assert_array_equal(result, audio)
        assert result is not audio


# ── 2. Paralinguistic ──────────────────────────────────────────────────────


class TestParseTags:
    def test_no_tags(self):
        from hevi.audio.paralinguistic import parse_tags

        result = parse_tags("Hello world")
        assert len(result) == 1
        assert result[0][0] == "Hello world"
        assert result[0][1] == []

    def test_single_tag(self):
        from hevi.audio.paralinguistic import parse_tags

        result = parse_tags("Hello [laugh] world")
        assert len(result) >= 2
        # Find the laugh tag
        tags = [t for _, ts in result for t in ts]
        tag_types = [t.tag_type for t in tags]
        assert "laugh" in tag_types

    def test_tag_with_param(self):
        from hevi.audio.paralinguistic import parse_tags

        result = parse_tags("Wait [pause:1.5] then continue")
        tags = [t for _, ts in result for t in ts]
        pause_tags = [t for t in tags if t.tag_type == "pause"]
        assert len(pause_tags) == 1
        assert pause_tags[0].param == "1.5"

    def test_closing_tag(self):
        from hevi.audio.paralinguistic import parse_tags

        result = parse_tags("[whisper]secret words[/whisper]")
        tags = [t for _, ts in result for t in ts]
        open_tags = [t for t in tags if t.tag_type == "whisper" and t.is_open]
        close_tags = [t for t in tags if t.tag_type == "whisper" and not t.is_open]
        assert len(open_tags) == 1
        assert len(close_tags) == 1

    def test_multiple_tags(self):
        from hevi.audio.paralinguistic import parse_tags

        result = parse_tags("[laugh] Ha! [sigh] Oh well [cough] excuse me")
        tags = [t for _, ts in result for t in ts]
        assert len(tags) >= 3


class TestStripTags:
    def test_strip_simple(self):
        from hevi.audio.paralinguistic import strip_tags

        assert strip_tags("Hello [laugh] world") == "Hello  world"

    def test_strip_all(self):
        from hevi.audio.paralinguistic import strip_tags

        assert strip_tags("[laugh][sigh][cough]") == ""

    def test_strip_closing(self):
        from hevi.audio.paralinguistic import strip_tags

        assert strip_tags("[whisper]secret[/whisper]") == "secret"

    def test_no_tags(self):
        from hevi.audio.paralinguistic import strip_tags

        assert strip_tags("Hello world") == "Hello world"


class TestExtractTextSegments:
    def test_basic(self):
        from hevi.audio.paralinguistic import extract_text_segments

        result = extract_text_segments("Hello [laugh] world")
        assert "Hello " in result or "Hello" in [s.strip() for s in result]


class TestGenerateTagAudio:
    def test_laugh(self):
        from hevi.audio.paralinguistic import generate_tag_audio

        audio = generate_tag_audio("laugh", sr=22050)
        assert len(audio) > 0
        assert audio.dtype == np.float32

    def test_sigh(self):
        from hevi.audio.paralinguistic import generate_tag_audio

        audio = generate_tag_audio("sigh", sr=22050)
        assert len(audio) > 0

    def test_gasp(self):
        from hevi.audio.paralinguistic import generate_tag_audio

        audio = generate_tag_audio("gasp", sr=22050)
        assert len(audio) > 0

    def test_cough(self):
        from hevi.audio.paralinguistic import generate_tag_audio

        audio = generate_tag_audio("cough", sr=22050)
        assert len(audio) > 0

    def test_unknown_tag(self):
        from hevi.audio.paralinguistic import generate_tag_audio

        audio = generate_tag_audio("unknown_tag_xyz", sr=22050)
        assert len(audio) > 0  # Returns short silence

    def test_all_known_tags(self):
        from hevi.audio.paralinguistic import generate_tag_audio, _TAG_AUDIO_GENERATORS

        for tag_type in _TAG_AUDIO_GENERATORS:
            audio = generate_tag_audio(tag_type, sr=22050)
            assert len(audio) > 0, f"tag {tag_type} produced empty audio"


class TestGetStyleOverride:
    def test_whisper(self):
        from hevi.audio.paralinguistic import get_style_override

        override = get_style_override("whisper")
        assert "rate" in override
        assert override["rate"] < 1.0

    def test_shout(self):
        from hevi.audio.paralinguistic import get_style_override

        override = get_style_override("shout")
        assert "volume" in override
        assert override["volume"] > 1.0

    def test_unknown(self):
        from hevi.audio.paralinguistic import get_style_override

        override = get_style_override("nonexistent")
        assert override == {}


class TestApplyParalinguistic:
    def test_no_tags(self):
        from hevi.audio.paralinguistic import apply_paralinguistic_to_audio

        sr = 22050
        audio = np.random.randn(sr).astype(np.float32) * 0.3
        result = apply_paralinguistic_to_audio("Hello world", audio, sr)
        np.testing.assert_array_equal(result, audio)

    def test_with_tags(self):
        from hevi.audio.paralinguistic import apply_paralinguistic_to_audio

        sr = 22050
        audio = np.random.randn(sr).astype(np.float32) * 0.3
        result = apply_paralinguistic_to_audio(
            "Hello [laugh] world", audio, sr
        )
        assert len(result) > len(audio)  # Should have added laugh audio

    def test_pause_tag(self):
        from hevi.audio.paralinguistic import apply_paralinguistic_to_audio

        sr = 22050
        audio = np.random.randn(sr).astype(np.float32) * 0.3
        result = apply_paralinguistic_to_audio(
            "Wait [pause:0.5] then go", audio, sr
        )
        expected_extra = int(sr * 0.5)
        assert len(result) >= len(audio) + expected_extra


# ── 3. Personality ──────────────────────────────────────────────────────────


class TestVoicePersona:
    def test_create(self):
        from hevi.audio.personality import VoicePersona

        persona = VoicePersona(
            name="Test",
            description="A test character",
            speaking_style="formal",
        )
        assert persona.name == "Test"
        assert persona.emotional_tendency == "neutral"

    def test_with_vocabulary(self):
        from hevi.audio.personality import VoicePersona

        persona = VoicePersona(
            name="Pirate",
            description="A pirate",
            vocabulary=["arr", "matey", "treasure"],
        )
        assert len(persona.vocabulary) == 3


class TestPresetPersonas:
    def test_list(self):
        from hevi.audio.personality import list_preset_personas

        personas = list_preset_personas()
        assert len(personas) >= 4
        assert "warrior" in personas
        assert "scholar" in personas

    def test_get_warrior(self):
        from hevi.audio.personality import get_preset_persona

        persona = get_preset_persona("warrior")
        assert persona is not None
        assert persona.name == "战士"
        assert len(persona.vocabulary) > 0

    def test_get_nonexistent(self):
        from hevi.audio.personality import get_preset_persona

        assert get_preset_persona("nonexistent") is None


class TestPersonalityEngine:
    def test_rule_based_rewrite(self):
        from hevi.audio.personality import PersonalityEngine, VoicePersona

        engine = PersonalityEngine()  # No LLM → rule-based
        persona = VoicePersona(
            name="Test",
            description="Test",
            speaking_style="粗犷直爽",
            vocabulary=["哈！"],
        )

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(
                engine.rewrite("请帮我把那个东西拿过来", persona)
            )
        finally:
            loop.close()

        assert result.original_text == "请帮我把那个东西拿过来"
        assert result.persona_name == "Test"
        assert result.model_used == "rule_based"

    def test_rule_based_compose(self):
        from hevi.audio.personality import PersonalityEngine, VoicePersona

        engine = PersonalityEngine()
        persona = VoicePersona(
            name="Test",
            description="Test",
            vocabulary=["好的", "没问题"],
        )

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(engine.compose(persona))
        finally:
            loop.close()

        assert result.persona_name == "Test"
        assert len(result.rewritten_text) > 0

    def test_llm_rewrite(self):
        from hevi.audio.personality import PersonalityEngine, VoicePersona

        mock_llm = AsyncMock(return_value="哈！把那个拿给俺！")
        engine = PersonalityEngine(llm_fn=mock_llm)
        persona = VoicePersona(
            name="Warrior",
            description="A warrior",
            speaking_style="粗犷",
        )

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(
                engine.rewrite("请把那个东西拿过来", persona)
            )
        finally:
            loop.close()

        assert result.rewritten_text == "哈！把那个拿给俺！"
        assert result.model_used == "llm"

    def test_llm_rewrite_failure_fallback(self):
        from hevi.audio.personality import PersonalityEngine, VoicePersona

        mock_llm = AsyncMock(side_effect=RuntimeError("LLM down"))
        engine = PersonalityEngine(llm_fn=mock_llm)
        persona = VoicePersona(name="Test", description="Test")

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(
                engine.rewrite("Hello world", persona)
            )
        finally:
            loop.close()

        assert result.rewritten_text == "Hello world"  # Fallback to original
        assert result.confidence == 0.5

    def test_respond(self):
        from hevi.audio.personality import PersonalityEngine, VoicePersona

        mock_llm = AsyncMock(return_value="俺可不怕！")
        engine = PersonalityEngine(llm_fn=mock_llm)
        persona = VoicePersona(name="Warrior", description="A warrior")

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(
                engine.respond("你害怕吗？", persona)
            )
        finally:
            loop.close()

        assert result.rewritten_text == "俺可不怕！"

    def test_empty_text(self):
        from hevi.audio.personality import PersonalityEngine, VoicePersona

        engine = PersonalityEngine()
        persona = VoicePersona(name="Test", description="Test")

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(engine.rewrite("", persona))
        finally:
            loop.close()

        assert result.rewritten_text == ""


# ── 4. Chatterbox Service ──────────────────────────────────────────────────


class TestChatterboxConfig:
    def test_default(self):
        from hevi.audio.chatterbox_service import ChatterboxConfig

        config = ChatterboxConfig()
        assert config.variant == "multilingual"
        assert config.sample_rate == 24000

    def test_turbo(self):
        from hevi.audio.chatterbox_service import ChatterboxConfig

        config = ChatterboxConfig(variant="turbo")
        assert config.variant == "turbo"


class TestChatterboxService:
    def test_multilingual_languages(self):
        from hevi.audio.chatterbox_service import ChatterboxService, ChatterboxConfig

        svc = ChatterboxService(ChatterboxConfig(variant="multilingual"))
        assert len(svc.supported_languages) == 23
        assert "en" in svc.supported_languages
        assert "zh" in svc.supported_languages
        assert "ar" in svc.supported_languages

    def test_turbo_languages(self):
        from hevi.audio.chatterbox_service import ChatterboxService, ChatterboxConfig

        svc = ChatterboxService(ChatterboxConfig(variant="turbo"))
        assert svc.supported_languages == ["en"]

    def test_turbo_paralinguistic(self):
        from hevi.audio.chatterbox_service import ChatterboxService, ChatterboxConfig

        turbo = ChatterboxService(ChatterboxConfig(variant="turbo"))
        multi = ChatterboxService(ChatterboxConfig(variant="multilingual"))
        assert turbo.supports_paralinguistic is True
        assert multi.supports_paralinguistic is False

    def test_synthesize_fallback(self, tmp_path):
        """Model not installed → generates silence."""
        from hevi.audio.chatterbox_service import ChatterboxService, ChatterboxConfig

        svc = ChatterboxService(ChatterboxConfig())
        output = tmp_path / "test.wav"

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(
                svc.synthesize("Hello world", output)
            )
        finally:
            loop.close()

        assert result == output
        assert output.exists()
        audio, sr = sf.read(str(output))
        assert sr == 24000

    def test_to_dict(self):
        from hevi.audio.chatterbox_service import ChatterboxService, ChatterboxConfig

        svc = ChatterboxService(ChatterboxConfig(variant="turbo"))
        d = svc.to_dict()
        assert d["variant"] == "turbo"
        assert d["supports_paralinguistic"] is True

    def test_unload(self):
        from hevi.audio.chatterbox_service import ChatterboxService, ChatterboxConfig

        svc = ChatterboxService()
        svc.unload()  # Should not crash even if not loaded
        assert svc._loaded is False


class TestChatterboxFactories:
    def test_create_multilingual(self):
        from hevi.audio.chatterbox_service import create_chatterbox_multilingual

        svc = create_chatterbox_multilingual(language="zh")
        assert svc.config.variant == "multilingual"
        assert svc.config.language == "zh"

    def test_create_turbo(self):
        from hevi.audio.chatterbox_service import create_chatterbox_turbo

        svc = create_chatterbox_turbo()
        assert svc.config.variant == "turbo"
        assert svc.config.language == "en"


# ── 5. Kokoro Service ──────────────────────────────────────────────────────


class TestKokoroConfig:
    def test_default(self):
        from hevi.audio.kokoro_service import KokoroConfig

        config = KokoroConfig()
        assert config.voice == "af_heart"
        assert config.device == "cpu"


class TestKokoroService:
    def test_languages(self):
        from hevi.audio.kokoro_service import KokoroService

        svc = KokoroService()
        assert "en" in svc.supported_languages
        assert "zh" in svc.supported_languages
        assert "ja" in svc.supported_languages

    def test_list_voices_all(self):
        from hevi.audio.kokoro_service import KokoroService

        svc = KokoroService()
        voices = svc.list_voices()
        assert len(voices) >= 40

    def test_list_voices_by_category(self):
        from hevi.audio.kokoro_service import KokoroService

        svc = KokoroService()
        american_female = svc.list_voices("american_female")
        assert len(american_female) >= 10
        assert "af_heart" in american_female

    def test_chinese_voices(self):
        from hevi.audio.kokoro_service import KokoroService

        svc = KokoroService()
        chinese = svc.list_voices("chinese_female")
        assert len(chinese) >= 2

    def test_synthesize_fallback(self, tmp_path):
        """Model not installed → generates silence."""
        from hevi.audio.kokoro_service import KokoroService

        svc = KokoroService()
        output = tmp_path / "test.wav"

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(
                svc.synthesize("Hello world", output)
            )
        finally:
            loop.close()

        assert result == output
        assert output.exists()
        audio, sr = sf.read(str(output))
        assert sr == 24000

    def test_to_dict(self):
        from hevi.audio.kokoro_service import KokoroService

        svc = KokoroService()
        d = svc.to_dict()
        assert d["voice"] == "af_heart"
        assert d["total_voices"] >= 40

    def test_unload(self):
        from hevi.audio.kokoro_service import KokoroService

        svc = KokoroService()
        svc.unload()
        assert svc._loaded is False


class TestKokoroFactory:
    def test_create_kokoro(self):
        from hevi.audio.kokoro_service import create_kokoro

        svc = create_kokoro(voice="zf_xiaoxiao", language="zh")
        assert svc.config.voice == "zf_xiaoxiao"
        assert svc.config.language == "zh"


# ── 6. AudioProvider 注册 ──────────────────────────────────────────────────


class TestAudioProviderEnum:
    def test_new_providers(self):
        from hevi.audio.audio_config import AudioProvider

        assert AudioProvider.CHATTERBOX_MULTILINGUAL == "chatterbox_multilingual"
        assert AudioProvider.CHATTERBOX_TURBO == "chatterbox_turbo"
        assert AudioProvider.KOKORO == "kokoro"
        assert AudioProvider.QWEN_TTS == "qwen_tts"

    def test_existing_providers(self):
        from hevi.audio.audio_config import AudioProvider

        assert AudioProvider.EDGE_TTS == "edge_tts"
        assert AudioProvider.VIBEVOICE == "vibevoice"


# ── 7. Integration: __init__.py 导出 ───────────────────────────────────────


class TestModuleExports:
    def test_effects_exports(self):
        from hevi.audio import EffectsChain, EffectConfig, apply_effects, apply_effects_to_array, list_effect_presets

        assert EffectsChain is not None
        assert apply_effects is not None

    def test_paralinguistic_exports(self):
        from hevi.audio import parse_tags, strip_tags, generate_tag_audio

        assert parse_tags is not None
        assert strip_tags is not None

    def test_personality_exports(self):
        from hevi.audio import VoicePersona, PersonalityEngine, list_preset_personas

        assert VoicePersona is not None
        assert PersonalityEngine is not None

    def test_chatterbox_exports(self):
        from hevi.audio import ChatterboxService, create_chatterbox_multilingual, create_chatterbox_turbo

        assert ChatterboxService is not None

    def test_kokoro_exports(self):
        from hevi.audio import KokoroService, create_kokoro

        assert KokoroService is not None
        assert create_kokoro is not None
