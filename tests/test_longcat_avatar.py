"""LongCat-Avatar 数字人能力测试 — 音频驱动 + prompt 工程 + 讲解段集成。

测试覆盖:
  - avatar_driver: 音频预处理/帧数计算/prompt构造/生成流程 (~14 tests)
  - narrator_prompts: 人设/手势推断/prompt构造/负面约束 (~12 tests)
  - narration_avatar: 集成配置/端到端流程 (~5 tests)

运行: .venv/bin/python -m pytest tests/test_longcat_avatar.py --noconftest -v
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Avatar Driver tests
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

from hevi.video.longcat.avatar_driver import (
    AudioPreprocessConfig,
    AvatarDriverResult,
    AvatarEncoder,
    AvatarFraming,
    AvatarGenConfig,
    build_avatar_gen_config,
    build_avatar_prompt,
    compute_audio_duration_frames,
    preprocess_audio_for_avatar,
    generate_avatar_video,
)


class TestAvatarEncoder:
    def test_enum_values(self):
        assert AvatarEncoder.WAV2VEC2 == "wav2vec2"
        assert AvatarEncoder.WHISPER == "whisper"


class TestAvatarFraming:
    def test_enum_values(self):
        assert AvatarFraming.HALF_BODY == "half_body"
        assert AvatarFraming.MEDIUM_SHOT == "medium_shot"
        assert AvatarFraming.CLOSE_UP == "close_up"


class TestAudioPreprocessConfig:
    def test_defaults(self):
        cfg = AudioPreprocessConfig()
        assert cfg.loudness_norm is True
        assert cfg.lufs == -23.0
        assert cfg.noise_floor_db == -45.0
        assert cfg.sample_rate == 16000

    def test_ffmpeg_loudness_filter(self):
        cfg = AudioPreprocessConfig(lufs=-20.0)
        assert "loudnorm" in cfg.ffmpeg_loudness_filter
        assert "-20" in cfg.ffmpeg_loudness_filter

    def test_ffmpeg_lowpass_filter(self):
        cfg = AudioPreprocessConfig(cutoff_hz=2500.0)
        assert "lowpass" in cfg.ffmpeg_lowpass_filter
        assert "2500" in cfg.ffmpeg_lowpass_filter

    def test_vocal_separation_default_off(self):
        cfg = AudioPreprocessConfig()
        assert cfg.vocal_separation is False


class TestAvatarGenConfig:
    def test_defaults(self):
        cfg = AvatarGenConfig()
        assert cfg.fps == 25
        assert cfg.num_frames == 93
        assert cfg.text_guidance_scale == 4.0
        assert cfg.audio_guidance_scale == 4.0

    def test_duration_per_segment(self):
        cfg = AvatarGenConfig(num_frames=93, fps=25)
        assert abs(cfg.duration_per_segment_s - 3.72) < 0.01

    def test_effective_steps_standard(self):
        cfg = AvatarGenConfig(use_distill=False, num_inference_steps=50)
        assert cfg.effective_steps == 50

    def test_effective_steps_distill(self):
        cfg = AvatarGenConfig(use_distill=True, num_inference_steps=50)
        assert cfg.effective_steps == 8

    def test_ref_img_index_default(self):
        cfg = AvatarGenConfig()
        assert cfg.ref_img_index == 10

    def test_mask_frame_range_default(self):
        cfg = AvatarGenConfig()
        assert cfg.mask_frame_range == 3


class TestBuildAvatarGenConfig:
    def test_basic_build(self):
        cfg = build_avatar_gen_config()
        assert cfg.encoder == AvatarEncoder.WHISPER
        assert cfg.framing == AvatarFraming.HALF_BODY

    def test_distill_build(self):
        cfg = build_avatar_gen_config(use_distill=True)
        assert cfg.text_guidance_scale == 1.0
        assert cfg.audio_guidance_scale == 1.0
        assert cfg.num_inference_steps == 8

    def test_custom_audio_guidance(self):
        cfg = build_avatar_gen_config(audio_guidance_scale=5.0)
        assert cfg.audio_guidance_scale == 5.0


class TestBuildAvatarPrompt:
    def test_basic_prompt(self):
        prompt = build_avatar_prompt(
            narration_text="今天讲一个故事",
            narrator_desc="一位年轻女性,黑色长发",
        )
        assert "一位年轻女性" in prompt
        assert "正在说话" in prompt
        assert "半身像" in prompt

    def test_with_style(self):
        prompt = build_avatar_prompt(
            narration_text="test",
            narrator_desc="test person",
            style="写实风格",
        )
        assert "写实风格" in prompt

    def test_framing_close_up(self):
        prompt = build_avatar_prompt(
            narration_text="test",
            framing=AvatarFraming.CLOSE_UP,
        )
        assert "近景" in prompt

    def test_action_hint_included(self):
        prompt = build_avatar_prompt(
            narration_text="test",
            action_hint="微微点头",
        )
        assert "微微点头" in prompt

    def test_expression_constraint_always_present(self):
        prompt = build_avatar_prompt(narration_text="test")
        assert "表情自然" in prompt
        assert "口型" in prompt


class TestComputeAudioDurationFrames:
    def test_with_real_wav(self, tmp_path):
        """用 ffmpeg 生成一个 2s 正弦波 WAV 测试。"""
        wav_path = tmp_path / "test.wav"
        loop = asyncio.new_event_loop()
        try:
            proc = loop.run_until_complete(
                asyncio.create_subprocess_exec(
                    "ffmpeg", "-y",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
                    "-ar", "16000", "-ac", "1",
                    str(wav_path),
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
            )
            loop.run_until_complete(proc.wait())
        finally:
            loop.close()
        # 如果 ffmpeg 不可用,跳过
        if not wav_path.exists():
            pytest.skip("ffmpeg not available")

        duration, frames = compute_audio_duration_frames(wav_path, fps=25)
        assert 1.5 < duration < 2.5
        assert 37 < frames < 63


class TestPreprocessAudio:
    @pytest.mark.asyncio
    async def test_preprocess_creates_output(self, tmp_path):
        """预处理应创建输出文件。"""
        # 生成测试 WAV
        src = tmp_path / "src.wav"
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
            "-ar", "16000", "-ac", "1",
            str(src),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
        if not src.exists():
            pytest.skip("ffmpeg not available")

        out = tmp_path / "out.wav"
        result = await preprocess_audio_for_avatar(src, out)
        assert result.exists()


class TestGenerateAvatarVideo:
    @pytest.mark.asyncio
    async def test_no_gen_fn_returns_error(self, tmp_path):
        """没有 gen_fn 应返回 error。"""
        audio = tmp_path / "audio.wav"
        audio.write_text("mock")
        ref = tmp_path / "ref.png"
        ref.write_text("mock")

        result = await generate_avatar_video(
            audio_path=audio,
            ref_image_path=ref,
            prompt="test prompt",
            output_path=tmp_path / "out.mp4",
            gen_fn=None,
        )
        assert not result.success
        assert "no gen_fn" in result.error

    @pytest.mark.asyncio
    async def test_with_mock_gen_fn(self, tmp_path):
        """mock gen_fn 应被正确调用。"""
        audio = tmp_path / "audio.wav"
        # 创建有效 WAV
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
            "-ar", "16000", "-ac", "1",
            str(audio),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
        if not audio.exists():
            audio.write_text("mock")

        ref = tmp_path / "ref.png"
        ref.write_text("mock")
        out = tmp_path / "out.mp4"

        calls: list[dict] = []

        async def mock_gen(**kwargs):
            calls.append(kwargs)
            p = Path(kwargs["output_path"])
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("mock_video")
            return p

        result = await generate_avatar_video(
            audio_path=audio,
            ref_image_path=ref,
            prompt="test prompt",
            output_path=out,
            gen_fn=mock_gen,
            preprocess_audio=False,  # 跳过 ffmpeg
        )
        assert result.success
        assert len(calls) == 1
        assert calls[0]["audio_guidance_scale"] == 4.0
        assert calls[0]["reference_image"] == ref


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Narrator Prompts tests
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

from hevi.video.longcat.narrator_prompts import (
    NARRATOR_PERSONAS,
    NarratorPersona,
    NarratorPromptConfig,
    build_narrator_negative,
    build_narrator_prompt,
    infer_gesture_from_text,
)


class TestNarratorPersonas:
    def test_ancient_historian_exists(self):
        assert "ancient_historian" in NARRATOR_PERSONAS

    def test_modern_narrator_exists(self):
        assert "modern_narrator" in NARRATOR_PERSONAS

    def test_full_description(self):
        p = NARRATOR_PERSONAS["ancient_historian"]
        desc = p.full_description()
        assert "史官" in desc
        assert "长袍" in desc
        assert "古代" in desc

    def test_female_narrator(self):
        p = NARRATOR_PERSONAS["female_narrator"]
        assert "女性" in p.description


class TestInferGesture:
    def test_number_gesture(self):
        g = infer_gesture_from_text("第一点是关于军事改革")
        assert "比划" in g

    def test_contrast_gesture(self):
        g = infer_gesture_from_text("但是结果却出乎意料")
        assert "摊开" in g

    def test_emphasis_gesture(self):
        g = infer_gesture_from_text("这是最关键的一步")
        assert "点头" in g

    def test_question_gesture(self):
        g = infer_gesture_from_text("为什么要这样做呢")
        assert "侧头" in g

    def test_sequence_gesture(self):
        g = infer_gesture_from_text("然后他做出了决定")
        assert "过渡" in g

    def test_no_gesture_for_plain_text(self):
        g = infer_gesture_from_text("天气很好阳光明媚")
        assert g == ""

    def test_max_two_gestures(self):
        text = "第一点是关键因素,但是为什么这么做呢"
        g = infer_gesture_from_text(text)
        parts = g.split(", ")
        assert len(parts) <= 2


class TestBuildNarratorPrompt:
    def test_basic_prompt(self):
        prompt = build_narrator_prompt("今天讲一个故事")
        assert "半身像" in prompt
        assert "说话" in prompt

    def test_with_persona(self):
        config = NarratorPromptConfig(
            persona=NARRATOR_PERSONAS["ancient_historian"]
        )
        prompt = build_narrator_prompt("商鞅变法", config)
        assert "史官" in prompt

    def test_with_style(self):
        config = NarratorPromptConfig(style="写实历史正剧")
        prompt = build_narrator_prompt("test", config)
        assert "写实历史正剧" in prompt

    def test_gesture_inference_enabled(self):
        config = NarratorPromptConfig(gesture_inference=True)
        prompt = build_narrator_prompt("第一点是重要的", config)
        assert "比划" in prompt or "点头" in prompt

    def test_gesture_inference_disabled(self):
        config = NarratorPromptConfig(gesture_inference=False)
        prompt = build_narrator_prompt("第一点是重要的", config)
        # 不应包含手势推断(但可能包含基础约束)
        assert "比划" not in prompt

    def test_expression_guard_present(self):
        config = NarratorPromptConfig(expression_guard=True)
        prompt = build_narrator_prompt("test", config)
        assert "表情自然" in prompt

    def test_custom_suffix(self):
        config = NarratorPromptConfig(custom_suffix="自定义描述")
        prompt = build_narrator_prompt("test", config)
        assert "自定义描述" in prompt

    def test_close_up_framing(self):
        config = NarratorPromptConfig(framing=AvatarFraming.CLOSE_UP)
        prompt = build_narrator_prompt("test", config)
        assert "近景" in prompt


class TestBuildNarratorNegative:
    def test_contains_quality_negatives(self):
        neg = build_narrator_negative()
        assert "worst quality" in neg
        assert "low quality" in neg

    def test_contains_motion_negatives(self):
        neg = build_narrator_negative()
        assert "jumping" in neg or "running" in neg

    def test_contains_mouth_negatives(self):
        neg = build_narrator_negative()
        assert "mouth" in neg


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Narration Avatar integration tests
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

from hevi.video.longcat.narration_avatar import (
    NarrationAvatarConfig,
    NarrationAvatarResult,
    build_narration_avatar_pipeline_config,
    generate_narration_avatar,
)


class TestNarrationAvatarConfig:
    def test_default_persona(self):
        cfg = NarrationAvatarConfig()
        assert cfg.persona.name == "ancient_historian"

    def test_custom_persona_key(self):
        cfg = NarrationAvatarConfig(persona_key="modern_narrator")
        assert cfg.persona.name == "modern_narrator"

    def test_unknown_persona_fallback(self):
        cfg = NarrationAvatarConfig(persona_key="nonexistent")
        # 回退到 ancient_historian
        assert cfg.persona.name == "ancient_historian"

    def test_custom_persona_object(self):
        custom = NarratorPersona(
            name="custom",
            description="自定义人物",
            clothing="自定义服饰",
            era="自定义时代",
        )
        cfg = NarrationAvatarConfig(custom_persona=custom)
        assert cfg.persona.name == "custom"


class TestBuildNarrationAvatarPipelineConfig:
    def test_basic_build(self):
        cfg = build_narration_avatar_pipeline_config()
        assert cfg.persona_key == "ancient_historian"
        assert not cfg.use_distill

    def test_with_style(self):
        cfg = build_narration_avatar_pipeline_config(style="写实风格")
        assert cfg.style == "写实风格"


class TestGenerateNarrationAvatar:
    @pytest.mark.asyncio
    async def test_no_gen_fn_graceful_error(self, tmp_path):
        """没有 gen_fn 应优雅失败(不崩溃)。"""
        audio = tmp_path / "tts.wav"
        audio.write_text("mock_audio")
        ref = tmp_path / "narrator.png"
        ref.write_text("mock_image")

        result = await generate_narration_avatar(
            tts_audio_path=audio,
            narrator_ref_image=ref,
            narration_text="这是一段讲解文本",
            output_dir=tmp_path / "output",
            gen_fn=None,
            shot_id="narr_01",
        )
        assert isinstance(result, NarrationAvatarResult)
        assert not result.success
        assert result.error is not None
        assert result.prompt != ""  # prompt 应该已构造

    @pytest.mark.asyncio
    async def test_with_mock_gen_fn(self, tmp_path):
        """mock gen_fn 端到端流程。"""
        # 创建有效 WAV(如果 ffmpeg 可用)
        audio = tmp_path / "tts.wav"
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "sine=frequency=880:duration=2",
            "-ar", "16000", "-ac", "1",
            str(audio),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
        if not audio.exists():
            audio.write_text("mock")

        ref = tmp_path / "narrator.png"
        ref.write_text("mock_image")

        calls: list[dict] = []

        async def mock_gen(**kwargs):
            calls.append(kwargs)
            p = Path(kwargs["output_path"])
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("mock_video")
            return p

        config = NarrationAvatarConfig(
            persona_key="ancient_historian",
            style="写实历史正剧",
        )
        result = await generate_narration_avatar(
            tts_audio_path=audio,
            narrator_ref_image=ref,
            narration_text="商鞅立木取信,这是变法的关键一步",
            output_dir=tmp_path / "output",
            config=config,
            gen_fn=mock_gen,
            shot_id="narr_01",
        )
        assert result.success
        assert len(calls) == 1
        # prompt 应包含人设描述
        assert "史官" in result.prompt
        # 应包含动作推断
        assert "点头" in result.prompt or "比划" in result.prompt
        # 应包含画风
        assert "写实历史正剧" in result.prompt
