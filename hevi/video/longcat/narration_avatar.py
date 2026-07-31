"""讲解段数字人升级 — 将静帧照片+口动替换为数字人半身像讲解。

Hevi 讲解段现状(qwen-image + TTS):
  ┌──────────────┐   ┌─────────┐   ┌──────────┐
  │ qwen-image   │──→│ 静帧照片 │──→│ 视频叠加 │
  │ 生成讲解空景  │   │ (不动)   │   │ +TTS音频 │
  └──────────────┘   └─────────┘   └──────────┘
  问题:照片不动,只有嘴在动(实际上是嘴也不动,音频直接叠加)

目标(本模块):
  ┌──────────────┐   ┌─────────────┐   ┌───────────────┐
  │ 讲解者参考图  │──→│ avatar_driver│──→│ 半身像讲解视频 │
  │ (半身肖像)   │   │ (音频驱动)  │   │ (口型+动作)   │
  └──────────────┘   └─────────────┘   └───────────────┘
  + TTS 音频输入 → 预处理 → 嵌入 → 驱动视频生成

使用方式:
  # 替换 tongjian_render / director_pipeline 中的讲解段生成逻辑:
  from hevi.video.longcat.narration_avatar import generate_narration_avatar

  result = await generate_narration_avatar(
      tts_audio_path=tts_output,         # TTS 生成的音频
      narrator_ref_image=narrator_portrait,  # 讲解者半身肖像
      narration_text=narration_text,     # 讲解文本
      output_dir=run_dir,
  )

对接 Hevi 已有后端:
  - gen_fn=avatar_generate (Duix 云端数字人)
  - gen_fn=wan_local_generate (wan_local VACE 参考条件化)
  - gen_fn=happyhorse_1_1_maas_reference_to_video (云端 reference-to-video)

LongCat-Avatar 参考机制:
  - 音频预处理(vocal 分离 + loudness norm + noise floor)
  - 音频嵌入(Whisper/Wav2Vec2)对齐到视频帧率
  - 双重引导(text + audio guidance_scale)
  - 参考图锚定(ref_img_index + mask_frame_range)
  - 多段续接(generate_avc, 长讲解)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Awaitable

from hevi.video.longcat.avatar_driver import (
    AvatarDriverResult,
    AvatarEncoder,
    AvatarFraming,
    AvatarGenConfig,
    build_avatar_gen_config,
    build_avatar_prompt,
    generate_avatar_video,
)
from hevi.video.longcat.narrator_prompts import (
    NARRATOR_PERSONAS,
    NarratorPersona,
    NarratorPromptConfig,
    build_narrator_negative,
    build_narrator_prompt,
)

logger = logging.getLogger(__name__)

__all__ = [
    "NarrationAvatarConfig",
    "NarrationAvatarResult",
    "generate_narration_avatar",
    "build_narration_avatar_pipeline_config",
]

# 类型:异步生成函数
GenFn = Callable[..., Awaitable[Path]]


@dataclass(frozen=True)
class NarrationAvatarConfig:
    """讲解段数字人配置。"""

    # 讲解者人设
    persona_key: str = "ancient_historian"  # 对应 NARRATOR_PERSONAS
    custom_persona: NarratorPersona | None = None

    # 生成参数
    framing: AvatarFraming = AvatarFraming.HALF_BODY
    resolution: tuple[int, int] = (480, 832)
    fps: int = 25

    # 画风
    style: str = ""  # 空=不指定,用后端默认

    # 音频驱动参数
    audio_guidance_scale: float = 4.0  # LongCat 推荐 3-5

    # 推理优化
    use_distill: bool = False
    use_int8: bool = False

    # 预处理
    preprocess_audio: bool = True

    # prompt 配置
    gesture_inference: bool = True
    expression_guard: bool = True
    custom_prompt_suffix: str = ""

    @property
    def persona(self) -> NarratorPersona:
        if self.custom_persona is not None:
            return self.custom_persona
        return NARRATOR_PERSONAS.get(
            self.persona_key,
            NARRATOR_PERSONAS["ancient_historian"],
        )


@dataclass
class NarrationAvatarResult:
    """讲解段数字人结果。"""

    video_path: Path | None = None
    audio_path: Path | None = None
    duration_s: float = 0.0
    prompt: str = ""
    negative_prompt: str = ""
    success: bool = False
    error: str | None = None
    config: NarrationAvatarConfig | None = None


def build_narration_avatar_pipeline_config(
    persona_key: str = "ancient_historian",
    style: str = "",
    resolution: tuple[int, int] = (480, 832),
    use_distill: bool = False,
) -> NarrationAvatarConfig:
    """构造讲解段数字人的管线配置。

    Args:
        persona_key: 讲解者人设键(对应 NARRATOR_PERSONAS)
        style: 画风描述
        resolution: 视频分辨率
        use_distill: 是否使用蒸馏采样(8步,更快但质量略低)

    Returns:
        NarrationAvatarConfig
    """
    return NarrationAvatarConfig(
        persona_key=persona_key,
        style=style,
        resolution=resolution,
        use_distill=use_distill,
    )


async def generate_narration_avatar(
    *,
    tts_audio_path: Path,
    narrator_ref_image: Path,
    narration_text: str,
    output_dir: Path,
    config: NarrationAvatarConfig | None = None,
    gen_fn: GenFn | None = None,
    shot_id: str = "narration",
) -> NarrationAvatarResult:
    """生成讲解段数字人半身像视频。

    这是讲解段升级的主入口。将原有的 qwen-image 静帧 + TTS 替换为:
      ref_image + TTS音频 + prompt → avatar_driver → 半身像讲解视频

    Args:
        tts_audio_path: TTS 生成的音频路径
        narrator_ref_image: 讲解者参考图(半身肖像,由 qwen-image 或 canon 生成)
        narration_text: 讲解文本(用于 prompt 构造 + 动作推断)
        output_dir: 输出目录
        config: 配置(None=默认古装史官)
        gen_fn: 视频生成函数(测试替身/切换后端)
        shot_id: 镜头标识

    Returns:
        NarrationAvatarResult
    """
    if config is None:
        config = NarrationAvatarConfig()

    output_dir.mkdir(parents=True, exist_ok=True)

    # 构造 prompt
    prompt_config = NarratorPromptConfig(
        persona=config.persona,
        framing=config.framing,
        style=config.style,
        gesture_inference=config.gesture_inference,
        expression_guard=config.expression_guard,
        custom_suffix=config.custom_prompt_suffix,
    )
    prompt = build_narrator_prompt(narration_text, prompt_config)
    negative = build_narrator_negative()

    # 构造 gen config
    avatar_config = build_avatar_gen_config(
        encoder=AvatarEncoder.WHISPER,
        framing=config.framing,
        resolution=config.resolution,
        fps=config.fps,
        audio_guidance_scale=config.audio_guidance_scale,
        use_distill=config.use_distill,
        use_int8=config.use_int8,
    )

    # 输出路径
    video_path = output_dir / f"{shot_id}_avatar.mp4"

    # 生成
    driver_result = await generate_avatar_video(
        audio_path=tts_audio_path,
        ref_image_path=narrator_ref_image,
        prompt=prompt,
        output_path=video_path,
        config=avatar_config,
        negative_prompt=negative,
        preprocess_audio=config.preprocess_audio,
        gen_fn=gen_fn,
    )

    return NarrationAvatarResult(
        video_path=driver_result.output_path,
        audio_path=driver_result.audio_preprocessed_path,
        duration_s=driver_result.duration_s,
        prompt=prompt,
        negative_prompt=negative,
        success=driver_result.success,
        error=driver_result.error,
        config=config,
    )
