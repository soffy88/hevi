"""krillinai oskill：组合 ≥2 个 oprim 原子，不得引用 omodul。

KrillinAI Clip Generator 技能：对应每个 CLI stage 的组合执行。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hevi.krillinai.oprim import (
    download_video,
    extract_audio,
    generate_cover,
    generate_short_mixed_srt,
    get_artifact_path,
    merge_tts_to_video,
    read_manifest,
    render_horizontal_bilingual,
    render_horizontal_dubbed,
    render_vertical,
    segment_subtitle,
    synthesize_tts,
    synthesize_with_aliyun_tts,
    synthesize_with_minimax_tts,
    synthesize_with_openai_tts,
    transcribe_audio,
    transcribe_with_faster_whisper,
    transcribe_with_whisper_cpp,
    translate_subtitle,
    write_manifest,
)
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
    TTSConfig,
    TTSProvider,
    VideoFile,
    make_clip_generator_job,
)

# ── Skill 1: 视频获取 + 音频提取 ─────────────────────────


def skill_acquire_video(
    job: ClipGeneratorJob,
) -> ClipGeneratorJob:
    """Stage: 获取视频并提取音频。

    对应 CLI: `krillinai-cli subtitle <input> --workdir ...`
    """
    job.update_status(JobStatus.DOWNLOADING, "acquire_video")

    # 1. 下载视频
    video = download_video(job.input_source, job.workdir)
    job.original_video = video

    # 2. 提取音频
    audio = extract_audio(video.path, job.workdir)
    job.original_audio = audio

    job.update_status(JobStatus.TRANSCRIBING, "extract_audio")
    write_manifest(job.workdir, job)
    return job


# ── Skill 2: 语音识别 ────────────────────────────────────


def skill_transcribe(
    job: ClipGeneratorJob,
) -> ClipGeneratorJob:
    """Stage: 语音识别生成字幕。

    对应 CLI: `krillinai-cli subtitle ...`
    """
    job.update_status(JobStatus.TRANSCRIBING, "transcribe")

    # 根据 ASR provider 选择实现
    provider = job.asr.provider
    if provider == ASRProvider.FASTER_WHISPER:
        srt = transcribe_with_faster_whisper(
            job.original_audio.path,
            model=job.asr.model,
            language=job.asr.language,
        )
    elif provider == ASRProvider.WHISPER_CPP:
        srt = transcribe_with_whisper_cpp(
            job.original_audio.path,
            model=job.asr.model,
        )
    else:
        # 统一接口
        srt = transcribe_audio(job.original_audio.path, job.asr)

    job.origin_language_srt = srt
    job.update_status(JobStatus.SEGMENTING, "transcribe")
    write_manifest(job.workdir, job)
    return job


# ── Skill 3: 智能分割 ────────────────────────────────────


def skill_segment(
    job: ClipGeneratorJob,
) -> ClipGeneratorJob:
    """Stage: LLM 智能字幕分段与对齐。

    对应 CLI: 内部处理，无单独命令
    """
    job.update_status(JobStatus.SEGMENTING, "segment")

    segmented = segment_subtitle(
        job.origin_language_srt.path,
        job.llm,
    )
    job.segmented_srt = segmented

    job.update_status(JobStatus.TRANSLATING, "segment")
    write_manifest(job.workdir, job)
    return job


# ── Skill 4: 专业翻译 ────────────────────────────────────


def skill_translate(
    job: ClipGeneratorJob,
) -> ClipGeneratorJob:
    """Stage: LLM 专业翻译 + 术语替换 + 双语字幕 + 短竖屏混合字幕。

    对应 CLI: `krillinai-cli subtitle ...` 的翻译步骤
    """
    job.update_status(JobStatus.TRANSLATING, "translate")

    target_lang = job.asr.language  # 简化：目标语言 = ASR 语言
    if target_lang == "auto":
        target_lang = "zh_cn"

    target, bilingual = translate_subtitle(
        job.segmented_srt.path,
        target_lang,
        job.llm,
        job.llm.terminology_map,
    )
    job.target_language_srt = target
    job.bilingual_srt = bilingual

    # 生成短竖屏混合字幕
    mixed = generate_short_mixed_srt(
        job.origin_language_srt.path,
        target.path,
    )
    job.short_origin_mixed_srt = mixed

    job.update_status(JobStatus.TTS_SYNTHESIZING, "translate")
    write_manifest(job.workdir, job)
    return job


# ── Skill 5: TTS 配音 ────────────────────────────────────


def skill_tts(
    job: ClipGeneratorJob,
    line_mode: str = "target-only",
) -> ClipGeneratorJob:
    """Stage: SRT 合成 TTS 音频 + 生成 video_with_tts.mp4。

    对应 CLI: `krillinai-cli tts --workdir ... --input-srt ... --video ...`
    """
    job.update_status(JobStatus.TTS_SYNTHESIZING, "tts")

    # 1. 合成 TTS 音频
    tts_audio = synthesize_tts(
        job.target_language_srt.path,
        job.tts,
        line_mode,
    )
    job.tts_final_audio = tts_audio

    # 2. 合并到视频
    if job.original_video.path:
        video_with_tts = merge_tts_to_video(
            job.original_video.path,
            tts_audio.path,
            str(Path(job.workdir) / "video_with_tts.mp4"),
        )
        job.video_with_tts = video_with_tts

    job.update_status(JobStatus.RENDERING, "tts")
    write_manifest(job.workdir, job)
    return job


# ── Skill 6: 视频合成 ────────────────────────────────────


def skill_render(
    job: ClipGeneratorJob,
    modes: list[RenderMode] | None = None,
) -> ClipGeneratorJob:
    """Stage: 视频渲染 (横屏/竖屏/双语/旁白)。

    对应 CLI: `krillinai-cli render-vertical` / `render-horizontal`
    """
    job.update_status(JobStatus.RENDERING, "render")

    modes = modes or [RenderMode.HORIZONTAL_BILINGUAL, RenderMode.VERTICAL_BILINGUAL]

    for mode in modes:
        if mode == RenderMode.HORIZONTAL_BILINGUAL:
            output = str(Path(job.workdir) / "horizontal_bilingual.mp4")
            result = render_horizontal_bilingual(
                job.original_video.path,
                job.bilingual_srt.path,
                output,
                job.render,
            )
            job.rendered_videos[mode] = result

        elif mode == RenderMode.HORIZONTAL_DUBBED:
            output = str(Path(job.workdir) / "horizontal_dubbed.mp4")
            result = render_horizontal_dubbed(
                job.video_with_tts.path if job.video_with_tts.path else job.original_video.path,
                output,
            )
            job.rendered_videos[mode] = result

        elif mode == RenderMode.VERTICAL_BILINGUAL:
            output = str(Path(job.workdir) / "vertical_bilingual.mp4")
            result = render_vertical(
                job.original_video.path,
                job.short_origin_mixed_srt.path,
                output,
                job.render,
            )
            job.rendered_videos[mode] = result

        elif mode == RenderMode.VERTICAL_DUBBED:
            output = str(Path(job.workdir) / "vertical_dubbed.mp4")
            result = render_vertical(
                job.video_with_tts.path if job.video_with_tts.path else job.original_video.path,
                job.target_language_srt.path,
                output,
                job.render,
                dubbed=True,
            )
            job.rendered_videos[mode] = result

    job.update_status(JobStatus.COVER_GENERATING, "render")
    write_manifest(job.workdir, job)
    return job


# ── Skill 7: 封面生成 ────────────────────────────────────


def skill_cover(
    job: ClipGeneratorJob,
    platforms: list[str] | None = None,
) -> ClipGeneratorJob:
    """Stage: 生成各平台封面。

    对应 CLI: `krillinai-cli cover`
    """
    job.update_status(JobStatus.COVER_GENERATING, "cover")

    platforms = platforms or [
        "bilibili", "xiaohongshu", "douyin", "shipinhao",
        "kuaishou", "youtube", "tiktok"
    ]

    for platform in platforms:
        output = str(Path(job.workdir) / f"cover_{platform}.jpg")
        cover = generate_cover(
            job.original_video.path,
            f"Platform cover for {platform}",
            platform,
            output,
        )
        job.covers.append(cover)

    job.update_status(JobStatus.COMPLETED, "cover")
    write_manifest(job.workdir, job)
    return job


# ── 完整 Pipeline 技能 ───────────────────────────────────


def skill_full_pipeline(
    job: ClipGeneratorJob,
    modes: list[RenderMode] | None = None,
    platforms: list[str] | None = None,
    line_mode: str = "target-only",
) -> ClipGeneratorJob:
    """完整 Clip Generator pipeline 执行。

    顺序执行所有 7 个 stage，每步写入 manifest。
    """
    # Stage 1: 视频获取
    job = skill_acquire_video(job)

    # Stage 2: 语音识别
    job = skill_transcribe(job)

    # Stage 3: 智能分割
    job = skill_segment(job)

    # Stage 4: 专业翻译
    job = skill_translate(job)

    # Stage 5: TTS 配音
    job = skill_tts(job, line_mode)

    # Stage 6: 视频合成
    job = skill_render(job, modes)

    # Stage 7: 封面生成
    job = skill_cover(job, platforms)

    return job


# ── 导出 ───────────────────────────────────────────────

__all__ = [
    "skill_acquire_video",
    "skill_cover",
    "skill_full_pipeline",
    "skill_render",
    "skill_segment",
    "skill_transcribe",
    "skill_translate",
    "skill_tts",
]