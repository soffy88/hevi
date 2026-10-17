"""音频驱动数字人 (Audio-Driven Avatar) — LongCat-Avatar 机制适配。

LongCat-Video-Avatar 核心能力:
  音频(Whisper/Wav2Vec2 嵌入) → DiT 模型 → 半身像说话视频(口型同步 + 自然动作)

Hevi 已有能力:
  - 演绎段(produce_v2):happyhorse-1.1 reference-to-video,走动说话的数字人 ✅
  - 讲解段(qwen-image):静态照片 + TTS 音频叠加,嘴不动 ❌
  - Duix:云端数字人口播(avatar_generate),但画质/口型精度有限

本模块目标:将讲解段从"照片+口动"升级为"数字人半身像讲解",参考 LongCat-Avatar 架构:

  ┌─────────────┐   ┌──────────────┐   ┌─────────────────┐
  │ TTS 音频     │──→│ 音频预处理    │──→│ 音频嵌入         │
  │ (edge_tts / │   │ loudness_norm│   │ Whisper/Wav2Vec2│
  │  vibevoice) │   │ noise_floor  │   │ fps 对齐         │
  └─────────────┘   │ smooth_trans │   └────────┬────────┘
                    └──────────────┘            │
  ┌─────────────┐                              │
  │ 讲解者参考图 │──────────────────────┐       │
  │ (半身像)    │                      ▼       ▼
  └─────────────┘              ┌─────────────────┐
                               │ 视频生成引擎     │
  ┌─────────────┐              │ (wan_local /    │
  │ 讲解 prompt  │─────────────→│  duix /         │
  │ (半身像+动作)│              │  happyhorse)    │
  └─────────────┘              └────────┬────────┘
                                        ▼
                               ┌─────────────────┐
                               │ 半身像讲解视频   │
                               │ (口型同步+动作) │
                               └─────────────────┘

关键机制(参考 LongCat-Avatar):
  1. 音频预处理:vocal 分离 + loudness 归一化 + noise floor + transient 平滑
  2. 音频嵌入:Whisper-Large-v3(v1.5)/ Wav2Vec2(v1.0)
  3. 双重引导:text_guidance_scale + audio_guidance_scale(3-5 最佳口型)
  4. 参考图锚定:ref_img_index=10, mask_frame_range=3(身份一致)
  5. 视频续接:generate_avc() 长讲解多段续接
  6. INT8 量化:VRAM 优化(本地 GPU 适配)
"""
from __future__ import annotations

import asyncio
import logging
import subprocess
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

__all__ = [
    "AvatarEncoder",
    "AvatarFraming",
    "AvatarGenConfig",
    "AudioPreprocessConfig",
    "AvatarDriverResult",
    "compute_audio_duration_frames",
    "build_avatar_prompt",
    "build_avatar_gen_config",
    "preprocess_audio_for_avatar",
    "generate_avatar_video",
]


class AvatarEncoder(StrEnum):
    """音频编码器(LongCat-Avatar v1.0=Wav2Vec2, v1.5=Whisper)。"""

    WAV2VEC2 = "wav2vec2"    # v1.0: chinese-wav2vec2-base, 口型基础精度
    WHISPER = "whisper"      # v1.5: Whisper-Large-v3, 更精准口型同步


class AvatarFraming(StrEnum):
    """半身像构图类型。"""

    HALF_BODY = "half_body"       # 标准半身像(讲解默认)
    MEDIUM_SHOT = "medium_shot"   # 中景(腰部以上)
    CLOSE_UP = "close_up"         # 近景(肩部以上)


@dataclass(frozen=True)
class AudioPreprocessConfig:
    """音频预处理配置(参考 LongCat-Avatar 预处理链路)。"""

    loudness_norm: bool = True
    lufs: float = -23.0           # EBU R128 响度标准
    noise_floor_db: float = -45.0 # 噪声底,防止静音段口型消失
    smooth_transients: bool = True
    cutoff_hz: float = 3000.0     # 低通截止频率
    vocal_separation: bool = False  # 分离人声(有BGM时有用,纯TTS不需要)
    sample_rate: int = 16000

    @property
    def ffmpeg_loudness_filter(self) -> str:
        """ffmpeg loudnorm 滤镜字符串。"""
        return f"loudnorm=I={self.lufs}:LRA=7:TP=-2"

    @property
    def ffmpeg_lowpass_filter(self) -> str:
        """ffmpeg lowpass 滤镜字符串。"""
        return f"lowpass=f={self.cutoff_hz}"


@dataclass(frozen=True)
class AvatarGenConfig:
    """数字人生成配置。"""

    # 基本参数
    encoder: AvatarEncoder = AvatarEncoder.WHISPER
    framing: AvatarFraming = AvatarFraming.HALF_BODY
    resolution: tuple[int, int] = (480, 832)  # (H, W)
    fps: int = 25          # LongCat-Avatar v1.5=25fps, v1.0=16fps
    num_frames: int = 93   # 93帧 @ 25fps ≈ 3.7s 一段

    # 引导参数(LongCat-Avatar 双引导)
    text_guidance_scale: float = 4.0
    audio_guidance_scale: float = 4.0  # 3-5 最佳口型(LongCat 文档推荐)

    # 参考图锚定(身份一致性)
    ref_img_index: int = 10       # 参考帧在视频中的位置(0-24:一致性, 30:减重复动作)
    mask_frame_range: int = 3     # 遮罩帧范围(3默认,增大可减重复动作但可能出伪影)

    # 续接参数(长讲解多段)
    num_cond_frames: int = 13     # 段间条件帧数
    use_kv_cache: bool = True     # KV cache 跨段传递(避免色彩漂移)

    # 推理优化
    use_distill: bool = False     # 蒸馏采样(8步 vs 50步)
    use_int8: bool = False        # INT8 量化(降 VRAM)
    num_inference_steps: int = 50

    # 音频预处理
    audio_preprocess: AudioPreprocessConfig = field(
        default_factory=AudioPreprocessConfig
    )

    @property
    def duration_per_segment_s(self) -> float:
        """每段视频时长(秒)。"""
        return self.num_frames / self.fps

    @property
    def effective_steps(self) -> int:
        """实际推理步数(蒸馏模式下为 8)。"""
        if self.use_distill:
            return 8
        return self.num_inference_steps


@dataclass
class AvatarDriverResult:
    """数字人驱动结果。"""

    output_path: Path | None = None
    audio_preprocessed_path: Path | None = None
    duration_s: float = 0.0
    num_segments: int = 1
    config: AvatarGenConfig | None = None
    success: bool = False
    error: str | None = None


def compute_audio_duration_frames(
    audio_path: Path,
    fps: int = 25,
    sample_rate: int = 16000,
) -> tuple[float, int]:
    """计算音频时长和对应帧数。

    Returns:
        (duration_s, num_frames)
    """
    # 用 ffprobe 获取时长(无需加载 numpy/scipy)
    try:
        proc = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(audio_path),
            ],
            capture_output=True, text=True, timeout=10,
        )
        duration = float(proc.stdout.strip())
    except Exception:
        # fallback: 文件大小 / (采样率 × 2 bytes)
        size = audio_path.stat().st_size
        duration = size / (sample_rate * 2)  # 16-bit mono

    num_frames = int(duration * fps)
    return duration, num_frames


async def preprocess_audio_for_avatar(
    audio_path: Path,
    output_path: Path,
    config: AudioPreprocessConfig | None = None,
) -> Path:
    """对 TTS 音频做 LongCat-Avatar 式预处理。

    处理链路(ffmpeg):
      1. loudness 归一化(EBU R128, -23 LUFS)
      2. noise floor(-45dB 白噪声,防止静音段口型消失)
      3. lowpass 3kHz(平滑瞬态,减少口型抖动)

    Args:
        audio_path: 输入音频(WAV/MP3)
        output_path: 输出音频路径
        config: 预处理配置(None=默认)

    Returns:
        预处理后的音频路径
    """
    if config is None:
        config = AudioPreprocessConfig()

    output_path.parent.mkdir(parents=True, exist_ok=True)

    filters: list[str] = []
    if config.loudness_norm:
        filters.append(config.ffmpeg_loudness_filter)
    if config.smooth_transients:
        filters.append(config.ffmpeg_lowpass_filter)

    filter_str = ",".join(filters) if filters else "anull"

    cmd = [
        "ffmpeg", "-y",
        "-i", str(audio_path),
        "-af", filter_str,
        "-ar", str(config.sample_rate),
        "-ac", "1",  # mono
        "-acodec", "pcm_s16le",
        str(output_path),
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    rc = await proc.wait()
    if rc != 0:
        logger.warning("avatar audio preprocess failed (rc=%d), using original", rc)
        import shutil
        shutil.copy2(audio_path, output_path)

    # noise floor: 用 ffmpeg amix 叠加极低音量白噪声
    if config.noise_floor_db < -30:
        noise_path = output_path.with_suffix(".noise.wav")
        noise_cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i",
            f"anoisesrc=color=white:amplitude={10 ** (config.noise_floor_db / 20)}:duration=600",
            "-ar", str(config.sample_rate), "-ac", "1",
            "-t", "600",
            str(noise_path),
        ]
        noise_proc = await asyncio.create_subprocess_exec(
            *noise_cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await noise_proc.wait()

        if noise_path.exists():
            mixed_path = output_path.with_suffix(".mixed.wav")
            mix_cmd = [
                "ffmpeg", "-y",
                "-i", str(output_path),
                "-i", str(noise_path),
                "-filter_complex", "amix=inputs=2:duration=first",
                "-ar", str(config.sample_rate), "-ac", "1",
                str(mixed_path),
            ]
            mix_proc = await asyncio.create_subprocess_exec(
                *mix_cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await mix_proc.wait()
            if mixed_path.exists():
                import shutil
                shutil.move(str(mixed_path), str(output_path))
            noise_path.unlink(missing_ok=True)

    return output_path


def build_avatar_prompt(
    narration_text: str,
    narrator_desc: str = "",
    framing: AvatarFraming = AvatarFraming.HALF_BODY,
    style: str = "",
    action_hint: str = "",
) -> str:
    """构造讲解数字人的视频生成 prompt。

    LongCat-Avatar 文档推荐:长描述性 prompt 效果更好,需包含角色外貌、动作、场景。
    示例:"A young woman with long black hair is speaking and smiling, wearing a
    white blouse, sitting in a bright café"

    Args:
        narration_text: 讲解文本(用于动作推断)
        narrator_desc: 讲解者外貌描述
        framing: 半身像构图
        style: 画风
        action_hint: 额外动作提示

    Returns:
        完整 prompt 文本
    """
    framing_desc = {
        AvatarFraming.HALF_BODY: "半身像,腰部以上可见",
        AvatarFraming.MEDIUM_SHOT: "中景,腰部以上",
        AvatarFraming.CLOSE_UP: "近景,肩部以上特写",
    }.get(framing, "半身像")

    # 基础 prompt(参考 LongCat-Avatar 推荐格式)
    parts: list[str] = []

    if narrator_desc:
        parts.append(narrator_desc)

    parts.append(framing_desc)
    parts.append("正在说话并伴有自然的手势和表情")

    if style:
        parts.append(style)

    if action_hint:
        parts.append(action_hint)

    # 半身像讲解的通用约束
    parts.append(
        "表情自然,口型与语音同步,身体有轻微自然的说话动作,不要大幅度运动"
    )

    return ", ".join(parts)


def build_avatar_gen_config(
    *,
    encoder: AvatarEncoder = AvatarEncoder.WHISPER,
    framing: AvatarFraming = AvatarFraming.HALF_BODY,
    resolution: tuple[int, int] = (480, 832),
    fps: int = 25,
    audio_guidance_scale: float = 4.0,
    use_distill: bool = False,
    use_int8: bool = False,
) -> AvatarGenConfig:
    """构造数字人生成配置。"""
    if use_distill:
        num_steps = 8
        text_gs = 1.0
        audio_gs = 1.0
    else:
        num_steps = 50
        text_gs = 4.0
        audio_gs = audio_guidance_scale

    return AvatarGenConfig(
        encoder=encoder,
        framing=framing,
        resolution=resolution,
        fps=fps,
        text_guidance_scale=text_gs,
        audio_guidance_scale=audio_gs,
        use_distill=use_distill,
        use_int8=use_int8,
        num_inference_steps=num_steps,
    )


async def generate_avatar_video(
    *,
    audio_path: Path,
    ref_image_path: Path,
    prompt: str,
    output_path: Path,
    config: AvatarGenConfig | None = None,
    negative_prompt: str = "",
    preprocess_audio: bool = True,
    gen_fn: Any = None,
) -> AvatarDriverResult:
    """生成数字人半身像讲解视频。

    这是主入口函数。流程:
      1. 音频预处理(loudness norm + noise floor + smooth)
      2. 调用视频生成引擎(ref_image + audio + prompt → video)
      3. 返回结果

    Args:
        audio_path: TTS 音频路径
        ref_image_path: 讲解者参考图(半身像)
        prompt: 视频生成 prompt
        output_path: 输出视频路径
        config: 生成配置(None=默认)
        negative_prompt: 负向 prompt
        preprocess_audio: 是否预处理音频
        gen_fn: 自定义生成函数(用于测试替身/切换后端)

    Returns:
        AvatarDriverResult
    """
    if config is None:
        config = build_avatar_gen_config()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    result = AvatarDriverResult(config=config)

    # ── Step 1: 音频预处理 ──────────────────────────────────────────────────
    processed_audio = audio_path
    if preprocess_audio:
        processed_audio = audio_path.with_stem(audio_path.stem + "_avatar_pp")
        processed_audio = await preprocess_audio_for_avatar(
            audio_path, processed_audio, config.audio_preprocess
        )
        result.audio_preprocessed_path = processed_audio

    # ── Step 2: 计算时长/帧数 ──────────────────────────────────────────────
    duration_s, num_frames = compute_audio_duration_frames(
        processed_audio, fps=config.fps
    )
    result.duration_s = duration_s

    # ── Step 3: 调用生成引擎 ──────────────────────────────────────────────
    if gen_fn is not None:
        try:
            await gen_fn(
                prompt=prompt,
                output_path=output_path,
                audio_path=processed_audio,
                reference_image=ref_image_path,
                size=config.resolution,
                frame_num=num_frames,
                num_inference_steps=config.effective_steps,
                text_guidance_scale=config.text_guidance_scale,
                audio_guidance_scale=config.audio_guidance_scale,
                negative_prompt=negative_prompt,
                ref_img_index=config.ref_img_index,
                mask_frame_range=config.mask_frame_range,
            )
            result.output_path = output_path
            result.success = True
        except Exception as e:
            logger.error("avatar generation failed: %s", e)
            result.error = str(e)
    else:
        # 默认:通过 Hevi 已有 avatar_generate (Duix) 或 wan_local (VACE)
        result.error = "no gen_fn provided; pass gen_fn=avatar_generate or custom backend"

    return result
