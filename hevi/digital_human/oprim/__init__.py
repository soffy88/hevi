"""digital_human oprim:无状态原子，不得引用 oskill/omodul。

对应 lanshu-create-ai-presenter-video 的 generation.md + generation 阶段逻辑。
每个函数是纯函数，无副作用，便于测试和组合。
"""

from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from hevi.digital_human.schemas import (
    AudioMeasurement,
    CaptionPhrase,
    CaptionPlan,
    ClipSpec,
    JobStatus,
    PresenterJob,
    QAReport,
    TimelinePlan,
    make_default_caption_plan,
    make_default_job,
    make_default_qa_report,
    make_default_timeline,
)

# ─── 内容锁定/文案原子 ──────────────────────────────


def lock_content(job: PresenterJob) -> PresenterJob:
    """锁定内容阶段。

    将主题或原始脚本转换为完整旁白，保存脚本与 Beat Sheet。
    对应 lanshu generation.md: "Lock content and audio"
    """
    from hevi.digital_human.oprim.narration import lock_content as _lock_content

    return _lock_content(job)


# ─── 声音/Narration 原子 ────────────────────────────


def generate_narration(
    job: PresenterJob,
    voice_id: str | None = None,
    rate: float | None = None,
) -> PresenterJob:
    """生成完整旁白。

    对应 lanshu generation.md: "Generate the complete approved narration"
    """
    # 更新音频配置
    if voice_id:
        job.voice_id = voice_id
    if rate is not None:
        job.rate = rate

    if job.final_audio and Path(job.final_audio).is_file():
        job.status = JobStatus.AUDIO_LOCKED
        job.updated_at = datetime.utcnow()
        return job
    if not job.script.strip():
        raise ValueError("cannot generate narration before content is locked")

    # HEVI native voice is a real, model-independent local renderer.  Neural
    # providers (Pocket TTS/VoxCPM/Voicebox) are selected by the task adapter;
    # this synchronous 3O atom uses the guaranteed local path and validates the
    # resulting WAV instead of manufacturing a path to a missing artifact.
    from hevi.voicepro.oskill import synthesize_native_voice_sync

    output_root = Path(
        os.getenv("HEVI_DIGITAL_HUMAN_OUTPUT_DIR", "data/digital_human")
    ).expanduser()
    output_path = output_root / job.job_id / "audio" / "narration.wav"
    synthesize_native_voice_sync(
        job.script,
        output_path,
        voice=job.voice_id,
        language=job.language,
        reference_audio=job.voice_sample or None,
        speed=job.rate,
    )
    if not output_path.is_file() or output_path.stat().st_size == 0:
        raise RuntimeError("native narration renderer produced no audio artifact")
    job.status = JobStatus.AUDIO_LOCKED
    job.updated_at = datetime.utcnow()
    job.final_audio = str(output_path)

    return job


def calibrate_audio_loudness(
    audio_path: str,
    target_lufs: float = -16,
) -> AudioMeasurement:
    """音频响度测量与校准（loudnorm 双遍）。

    对应 lanshu generation.md + editing.md 的响度归一化
    """
    from hevi.digital_human.oprim.qa import check_audio_loudness

    result = check_audio_loudness(audio_path, target_lufs=target_lufs)
    if not result.get("ok"):
        raise RuntimeError(str(result.get("error") or "audio loudness measurement failed"))
    return AudioMeasurement(
        input_i=float(result["measured_lufs"]),
        input_tp=float(result.get("input_tp") or 0.0),
        input_lra=float(result.get("input_lra") or 0.0),
        input_thresh=float(result.get("input_thresh") or 0.0),
        target_offset=float(result.get("target_offset") or 0.0),
        measured_lufs=float(result["measured_lufs"]),
        program_lufs=target_lufs,
    )


# ─── 时间轴/剪辑原子 ──────────────────────────────


def build_timeline(
    job: PresenterJob,
    narration_duration_s: float,
    opening_target_s: float = 4.0,
    closing_target_s: float = 5.0,
) -> TimelinePlan:
    """构建确定性时间轴。

    对应 lanshu editing.md: "Timeline contract" - 音频为主时钟
    """
    # 计算主体时长 = 总时长 - 开场 - 结尾
    narration_duration_s - opening_target_s - closing_target_s

    timeline = TimelinePlan(
        narration_duration_s=narration_duration_s,
        total_video_duration_s=narration_duration_s,
        opening_target_s=opening_target_s,
        closing_target_s=closing_target_s,
    )

    # 更新作业 timeline
    job.timeline = timeline.model_dump_json()
    job.updated_at = datetime.utcnow()

    return timeline


def add_clip_to_timeline(
    timeline: TimelinePlan,
    authored_start_s: float,
    authored_duration_s: float,
    source_start_s: float,
    source_duration_s: float,
    media_path: str,
    media_type: str = "video",
) -> TimelinePlan:
    """添加剪辑到时间轴。

    承担 ClipSpec 三独立值：authored_start, authored_duration, source_start
    """
    clip = ClipSpec(
        authored_start_s=authored_start_s,
        authored_duration_s=authored_duration_s,
        source_start_s=source_start_s,
        source_duration_s=source_duration_s,
        media_path=media_path,
        media_type=media_type,
    )

    if not clip.is_valid():
        raise ValueError(f"Invalid clip spec: {clip}")

    timeline.clips.append(clip)
    return timeline


# ─── 字幕原子 ──────────────────────────────────────


def build_caption_plan(
    audio_duration_s: float,
    script_text: str,
    keyword_anchors: list[tuple[float, str]] | None = None,
) -> CaptionPlan:
    """构建字幕计划。

    从脚本文本生成词级时间戳 + 关键词动效预设绑定
    对应 lanshu editing.md: "Captions" + "Presenter-side keyword presets"
    """
    from hevi.digital_human.oprim.caption import KEYWORD_PRESETS, split_into_phrases

    # 分割为短语
    phrases = split_into_phrases(script_text, audio_duration_s)

    # 默认关键词预设
    presets = list(KEYWORD_PRESETS)

    # 为每个短语分配关键词预设（轮播）
    for i, phrase in enumerate(phrases):
        phrase.style = presets[i % len(presets)]

    return CaptionPlan(
        phrases=phrases,
        keyword_presets=presets,
    )


# ─── QA 原子 ───────────────────────────────────────


def run_preflight_check(job: PresenterJob) -> QAReport:
    """运行预检查。

    对应 Lanshu 的 preflight.py + generation.md QA 门控
    """
    from hevi.digital_human.oprim.qa import check_authorization, check_media_technical

    report = QAReport()

    # 授权检查
    auth_ok = check_authorization(job)
    report.rights_confirmed = auth_ok.get("rights_confirmed", False)
    report.adult_presenter_confirmed = auth_ok.get("adult_presenter_confirmed", False)
    report.remote_upload_approved = auth_ok.get("remote_upload_approved", False)
    report.voice_clone_approved = auth_ok.get("voice_clone_approved", False)

    # 技术检查
    media_ok = check_media_technical(job)
    report.errors = media_ok.get("errors", [])
    report.warnings = media_ok.get("warnings", [])
    report.media = media_ok.get("media", {})

    report.remote_ready = auth_ok.get("remote_ready", False) and not report.errors
    report.ok = not report.errors and report.remote_ready

    return report


def run_qa_gate(
    job: PresenterJob,
    identity_coherent: bool = True,
    mouth_sync: bool = True,
    no_black_frames: bool = True,
    no_overlay: bool = True,
    captions_readable: bool = True,
    safe_zones_ok: bool = True,
) -> QAReport:
    """运行完整 QA 验收门控。

    对应 lanshu qa-recovery.md: "Acceptance gates"
    """
    report = QAReport()

    # 技术错误/警告累积
    all_errors: list[str] = []
    all_warnings: list[str] = []

    # 身份/口型/黑帧/字幕/安全区检查
    checks = {
        "identity_coherent": identity_coherent,
        "mouth_sync": mouth_sync,
        "no_black_frames": no_black_frames,
        "no_overlay": no_overlay,
        "captions_readable": captions_readable,
        "safe_zones_ok": safe_zones_ok,
    }

    for check_name, passed in checks.items():
        if not passed:
            all_errors.append(f"FAILED: {check_name}")

    for label, media_path in (("final_audio", job.final_audio), ("rendered", job.rendered)):
        if media_path and (
            not Path(media_path).is_file() or Path(media_path).stat().st_size == 0
        ):
            all_errors.append(f"FAILED: {label}_artifact_missing")

    # 累积报告中的错误
    all_errors.extend(report.errors)
    all_warnings.extend(report.warnings)

    report.errors = all_errors
    report.warnings = all_warnings
    report.ok = len(all_errors) == 0
    report.identity_coherent = identity_coherent
    report.mouth_sync = mouth_sync
    report.no_black_frames = no_black_frames
    report.no_overlay = no_overlay
    report.captions_readable = captions_readable
    report.safe_zones_ok = safe_zones_ok

    # remote_ready: 通过授权 + 无技术错误
    report.remote_ready = (
        job.rights_confirmed
        and job.adult_presenter_confirmed
        and job.remote_upload_approved
        and job.voice_clone_approved
        and report.ok
    )

    return report
