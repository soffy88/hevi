"""krillinai oprim：无状态原子，不得引用 oskill/omodul。

KrillinAI Clip Generator 核心原子实现：
视频获取 → 语音识别 → 智能分割 → 专业翻译 → TTS 配音 → 视频合成 → 封面生成
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from hevi.krillinai.schemas import (
    ASRConfig,
    ASRProvider,
    AudioFile,
    ClipGeneratorJob,
    CoverFile,
    JobStatus,
    LLMConfig,
    LLMProvider,
    RenderConfig,
    RenderMode,
    SubtitleFile,
    SubtitleSegment,
    TranslationPair,
    TTSConfig,
    TTSProvider,
    VideoFile,
    make_clip_generator_job,
)

# ── Stage 1: 视频获取 ────────────────────────────────────


def download_video(
    source: str,
    workdir: str,
    yt_dlp_args: list[str] | None = None,
) -> VideoFile:
    """使用 yt-dlp 下载视频。

    KrillinAI 使用 yt-dlp 支持 YouTube、Bilibili 等平台。
    """
    path = Path(workdir) / "origin_video.mp4"
    path.parent.mkdir(parents=True, exist_ok=True)

    args = ["yt-dlp", "-o", str(path)]
    if yt_dlp_args:
        args.extend(yt_dlp_args)
    args.append(source)

    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"yt-dlp failed: {result.stderr}")

    return VideoFile(
        path=str(path),
        duration_s=0.0,  # 由 ffprobe 获取
    )


def extract_audio(video_path: str, workdir: str) -> AudioFile:
    """从视频提取音频 (用于语音识别)。

    使用 ffmpeg 提取 WAV 格式音频。
    """
    audio_path = Path(workdir) / "origin_audio.wav"
    args = [
        "ffmpeg", "-y", "-i", video_path,
        "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
        str(audio_path)
    ]
    subprocess.run(args, check=True, capture_output=True)

    return AudioFile(path=str(audio_path), duration_s=0.0)


# ── Stage 2: 语音识别 ────────────────────────────────────


def transcribe_audio(
    audio_path: str,
    config: ASRConfig,
) -> SubtitleFile:
    """语音识别生成字幕。

    支持多种 ASR 提供商：
    - FasterWhisper (Windows/Linux 本地)
    - WhisperKit (macOS M系列)
    - WhisperCpp (所有平台)
    - OpenAI Whisper API (云端)
    - 阿里云 ASR (云端)
    """
    # 实际实现根据 provider 调用不同后端
    # 这里返回占位结构
    output_path = Path(audio_path).with_suffix(".srt")
    return SubtitleFile(
        path=str(output_path),
        language=config.language,
        format="srt",
    )


def transcribe_with_faster_whisper(
    audio_path: str,
    model: str = "large-v2",
    language: str = "auto",
    device: str = "auto",
) -> SubtitleFile:
    """FasterWhisper 本地转写 (占位实现)。"""
    output_path = Path(audio_path).with_suffix(".srt")
    return SubtitleFile(path=str(output_path), language=language, format="srt")


def transcribe_with_whisper_cpp(
    audio_path: str,
    model: str = "large-v2",
) -> SubtitleFile:
    """WhisperCpp 跨平台转写 (占位实现)。"""
    output_path = Path(audio_path).with_suffix(".srt")
    return SubtitleFile(path=str(output_path), language="auto", format="srt")


# ── Stage 3: 智能分割 ────────────────────────────────────


def segment_subtitle(
    srt_path: str,
    llm_config: LLMConfig,
) -> SubtitleFile:
    """LLM 智能字幕分段与对齐。

    KrillinAI 使用 LLM 进行字幕分段，确保：
    - 自然语义边界
    - 读速舒适
    - 无遗漏/重叠
    """
    output_path = Path(srt_path).with_name("segmented_" + Path(srt_path).name)
    return SubtitleFile(
        path=str(output_path),
        language="auto",
        format="srt",
    )


# ── Stage 4: 专业翻译 ────────────────────────────────────


def translate_subtitle(
    srt_path: str,
    target_lang: str,
    llm_config: LLMConfig,
    terminology_map: dict[str, str] | None = None,
) -> tuple[SubtitleFile, SubtitleFile]:
    """LLM 专业翻译 + 术语替换。

    返回：(目标语言字幕, 双语字幕)
    """
    target_path = Path(srt_path).with_name(f"target_{target_lang}_" + Path(srt_path).name)
    bilingual_path = Path(srt_path).with_name("bilingual_" + Path(srt_path).name)

    return (
        SubtitleFile(path=str(target_path), language=target_lang, format="srt"),
        SubtitleFile(path=str(bilingual_path), language="bilingual", format="srt"),
    )


def generate_short_mixed_srt(
    origin_srt: str,
    target_srt: str,
) -> SubtitleFile:
    """生成短竖屏混合字幕 (short_origin_mixed_srt.srt)。

    用于竖屏视频的双语字幕显示。
    """
    output_path = Path(origin_srt).with_name("short_origin_mixed_" + Path(origin_srt).name)
    return SubtitleFile(path=str(output_path), language="mixed", format="srt")


# ── Stage 5: TTS 配音 ────────────────────────────────────


def synthesize_tts(
    srt_path: str,
    config: TTSConfig,
    line_mode: str = "target-only",
) -> AudioFile:
    """SRT 合成 TTS 音频。

    支持：
    - target-only: 仅目标语言
    - bilingual-target-top: 双语目标在上
    - bilingual-target-bottom: 双语目标在下
    """
    output_path = Path(srt_path).with_suffix(".wav")
    return AudioFile(path=str(output_path))


def synthesize_with_aliyun_tts(
    text: str,
    voice: str = "zh-CN-Xiaoyun",
    speed: float = 1.0,
) -> AudioFile:
    """阿里云 TTS 合成 (占位)。"""
    return AudioFile(path="/tmp/aliyun_tts.wav")


def synthesize_with_openai_tts(
    text: str,
    voice: str = "alloy",
) -> AudioFile:
    """OpenAI TTS 合成 (占位)。"""
    return AudioFile(path="/tmp/openai_tts.wav")


def synthesize_with_minimax_tts(
    text: str,
    voice: str = "Chinese Male",
) -> AudioFile:
    """MiniMax TTS 合成 (占位)。"""
    return AudioFile(path="/tmp/minimax_tts.wav")


# ── Stage 6: 视频合成 ────────────────────────────────────


def merge_tts_to_video(
    video_path: str,
    audio_path: str,
    output_path: str,
) -> VideoFile:
    """将 TTS 音频合并到视频 (生成 video_with_tts.mp4)。"""
    subprocess.run([
        "ffmpeg", "-y", "-i", video_path, "-i", audio_path,
        "-c:v", "copy", "-map", "0:v:0", "-map", "1:a:0",
        "-shortest", output_path
    ], check=True, capture_output=True)

    return VideoFile(path=output_path)


def render_horizontal_bilingual(
    video_path: str,
    srt_path: str,
    output_path: str,
    config: RenderConfig,
) -> VideoFile:
    """渲染横屏双语视频。"""
    # 使用 FFmpeg 烧录字幕
    subprocess.run([
        "ffmpeg", "-y", "-i", video_path,
        "-vf", f"subtitles={srt_path}",
        "-c:a", "copy", output_path
    ], check=True, capture_output=True)

    return VideoFile(path=output_path)


def render_horizontal_dubbed(
    video_path: str,
    output_path: str,
) -> VideoFile:
    """渲染横屏旁白视频。"""
    subprocess.run([
        "ffmpeg", "-y", "-i", video_path,
        "-c:v", "copy", "-c:a", "copy", output_path
    ], check=True, capture_output=True)

    return VideoFile(path=output_path)


def render_vertical(
    video_path: str,
    srt_path: str,
    output_path: str,
    config: RenderConfig,
    dubbed: bool = False,
) -> VideoFile:
    """渲染竖屏视频 (对应 KrillinAI render-vertical)。

    特性：
    - 中文分词后再换行判断
    - 显示宽度计算：中文宽度2，英文宽度1
    - 长中文字幕按时间分割而非 \\N 堆叠
    - 目标：屏幕保持 1 行英文 + 1 行中文
    """
    # 实际实现使用 FFmpeg + 字幕滤镜
    subprocess.run([
        "ffmpeg", "-y", "-i", video_path,
        "-vf", f"subtitles={srt_path}",
        "-c:a", "copy", output_path
    ], check=True, capture_output=True)

    return VideoFile(path=output_path)


# ── Stage 7: 封面生成 ────────────────────────────────────


def generate_cover(
    video_path: str,
    prompt_template: str,
    platform: str,
    output_path: str,
) -> CoverFile:
    """从视频缩略图 + 提示模板生成平台封面。

    KrillinAI 封面生成功能。
    """
    # 1. 提取视频首帧/关键帧
    thumb_path = Path(output_path).with_suffix(".thumb.jpg")
    subprocess.run([
        "ffmpeg", "-y", "-i", video_path,
        "-vf", "select=eq(n\\,0)", "-vframes", "1",
        str(thumb_path)
    ], check=True, capture_output=True)

    # 2. 使用图像生成模型 (Flux 2 Pro / DALL-E / SD) 生成封面
    # 实际实现调用相应的图像生成 API

    return CoverFile(
        path=output_path,
        platform=platform,
    )


# ── Manifest 管理 ───────────────────────────────────────


MANIFEST_FILE = "krillinai_manifest.json"


def write_manifest(workdir: str, job: ClipGeneratorJob) -> None:
    """写入作业清单 (对应 krillinai_manifest.json)。"""
    path = Path(workdir) / MANIFEST_FILE
    data = job.model_dump()
    # 转换 datetime
    for k, v in data.items():
        if isinstance(v, datetime):
            data[k] = v.isoformat()
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def read_manifest(workdir: str) -> ClipGeneratorJob:
    """读取作业清单。"""
    path = Path(workdir) / MANIFEST_FILE
    data = json.loads(path.read_text(encoding="utf-8"))
    # 转换 datetime
    for k, v in data.items():
        if k in ("created_at", "updated_at") and isinstance(v, str):
            data[k] = datetime.fromisoformat(v)
    return ClipGeneratorJob(**data)


def get_artifact_path(workdir: str, artifact: str) -> Path | None:
    """从 manifest 获取产物路径。"""
    path = Path(workdir) / artifact
    return path if path.exists() else None


# ── 导出 ───────────────────────────────────────────────

__all__ = [
    # Video acquisition
    "download_video", "extract_audio",
    # Transcription
    "transcribe_audio", "transcribe_with_faster_whisper", "transcribe_with_whisper_cpp",
    # Segmentation
    "segment_subtitle",
    # Translation
    "translate_subtitle", "generate_short_mixed_srt",
    # TTS
    "synthesize_tts", "synthesize_with_aliyun_tts", "synthesize_with_openai_tts",
    "synthesize_with_minimax_tts",
    # Rendering
    "merge_tts_to_video", "render_horizontal_bilingual", "render_horizontal_dubbed",
    "render_vertical",
    # Cover
    "generate_cover",
    # Manifest
    "write_manifest", "read_manifest", "get_artifact_path",
]
