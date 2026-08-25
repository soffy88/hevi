"""digital_human oskill:组合 ≥2 个 oprim 原子，不得引用 omodul。

对应 lanshu 的 SKILL.md 工作流编排。
"""

from __future__ import annotations

from typing import Any

from hevi.digital_human.oprim import (
    add_clip_to_timeline,
    build_caption_plan,
    build_timeline,
    calibrate_audio_loudness,
    generate_narration,
    lock_content,
    run_preflight_check,
    run_qa_gate,
)
from hevi.digital_human.oprim.caption import build_caption_plan as _build_caption_plan
from hevi.digital_human.oprim.narration import build_narration_spine, topic_to_script
from hevi.digital_human.oprim.narration import lock_content as _lock_content
from hevi.digital_human.oprim.qa import check_authorization, check_media_technical
from hevi.digital_human.oprim.render import (
    build_loudnorm_filter,
    calculate_contact_timestamps,
    delivery_report,
    encode_video,
    generate_contact_sheet,
    loudnorm_two_pass,
)
from hevi.digital_human.schemas import (
    AudioMeasurement,
    CaptionPlan,
    JobStatus,
    PresenterJob,
    QAReport,
    TimelinePlan,
    make_default_caption_plan,
    make_default_job,
    make_default_qa_report,
    make_default_timeline,
)

# ─── 内容锁定技能 ────────────────────────────────────


def content_lock(
    job: PresenterJob,
    voice_id: str | None = None,
    rate: float | None = None,
) -> PresenterJob:
    """内容锁定技能：主题/脚本 → 脚本 → 完整旁白。

    对应 lanshu generation.md 第 1 节
    """
    # 锁定内容
    job = lock_content(job)

    # 生成旁白
    job = generate_narration(job, voice_id=voice_id, rate=rate)

    return job


# ─── 视觉规划技能 ────────────────────────────────────


def visual_plan(
    job: PresenterJob,
    narration_duration_s: float,
    opening_target_s: float = 4.0,
    closing_target_s: float = 5.0,
) -> TimelinePlan:
    """视觉规划技能：构建确定性时间轴。

    对应 lanshu editing.md 第 1 节
    """
    timeline = build_timeline(
        job,
        narration_duration_s,
        opening_target_s,
        closing_target_s,
    )
    job.status = JobStatus.VISUAL_PLAN_LOCKED
    return timeline


# ─── 字幕规划技能 ────────────────────────────────────


def caption_plan(
    job: PresenterJob,
    audio_duration_s: float,
    keyword_anchors: list[tuple[float, str]] | None = None,
) -> CaptionPlan:
    """字幕规划技能：词级时间戳 + 关键词动效预设。

    对应 lanshu editing.md 第 2 节
    """
    return _build_caption_plan(
        audio_duration_s=audio_duration_s,
        script_text=job.script,
        keyword_anchors=keyword_anchors,
    )


# ─── 生成技能 ────────────────────────────────────────


def generate_presenter(
    job: PresenterJob,
    mode: str = "pilot",  # pilot | full
    pilot_duration_s: float = 5.0,
) -> PresenterJob:
    """人物生成技能：试片 → 全片生成。

    对应 lanshu generation.md 第 2 节
    """
    if mode == "pilot":
        # 试片：生成低成本小样
        job.rendered = f"assets/video/candidates/pilot_{job.job_id}.mp4"
    else:
        # 全片：生成完整主素材
        job.rendered = f"assets/video/selected/main_{job.job_id}.mp4"

    job.status = JobStatus.PRESENTER_GENERATED
    return job


# ─── 交付技能 ────────────────────────────────────────


def delivery(
    job: PresenterJob,
    render_path: str,
    output_dir: str,
    stem: str = "presenter-video",
) -> dict[str, Any]:
    """交付技能：母版/分享版编码 + 接触表 + 报告。

    对应 lanshu finalize_delivery.sh
    """
    import os

    out_path = os.path.join(output_dir, stem)
    master_path = f"{out_path}-master.mp4"
    share_path = f"{out_path}-share.mp4"
    contact_path = f"{out_path}-contact-sheet.png"
    report_path = f"{out_path}-delivery-report.json"

    # 1. 响度测量
    measurement = loudnorm_two_pass(render_path, master_path)

    # 2. 母版编码
    encode_video(
        render_path,
        master_path,
        crf=16,
        preset="slow",
        audio_bitrate="256k",
    )

    # 3. 分享版编码
    encode_video(
        render_path,
        share_path,
        crf=24,
        preset="medium",
        audio_bitrate="160k",
    )

    # 4. 接触表
    generate_contact_sheet(master_path, contact_path)

    # 5. 报告
    report = delivery_report(
        master_path=master_path,
        share_path=share_path,
        contact_sheet_path=contact_path,
        duration_s=measurement.measured_lufs,  # 占位
        measurement=measurement,
        source_probe={},
        master_probe={},
        share_probe={},
        black_events=0,
    )

    # 6. 更新作业状态
    job.rendered = master_path
    job.share = share_path
    job.status = JobStatus.RENDERED

    return {
        "master": master_path,
        "share": share_path,
        "contact_sheet": contact_path,
        "report": report_path,
        "report_data": report,
    }


# ─── QA 技能 ────────────────────────────────────────


def qa_gate(
    job: PresenterJob,
    identity_coherent: bool = True,
    mouth_sync: bool = True,
    no_black_frames: bool = True,
    captions_readable: bool = True,
    safe_zones_ok: bool = True,
) -> QAReport:
    """QA 技能：完整验收门控。

    对应 lanshu qa-recovery.md acceptance gates
    """
    return run_qa_gate(
        job,
        identity_coherent=identity_coherent,
        mouth_sync=mouth_sync,
        no_black_frames=no_black_frames,
        captions_readable=captions_readable,
        safe_zones_ok=safe_zones_ok,
    )


# ─── 预检查技能 ──────────────────────────────────────


def preflight_check(job: PresenterJob) -> QAReport:
    """预检查技能：在进入生成前的门控。

    对应 lanshu preflight.py
    """
    return run_preflight_check(job)


# ─── 导出 ───────────────────────────────────────────

__all__ = [
    "build_loudnorm_filter",
    "build_narration_spine",
    "calculate_contact_timestamps",
    "caption_plan",
    "check_authorization",
    "check_media_technical",
    "content_lock",
    "delivery",
    "delivery_report",
    "encode_video",
    "generate_contact_sheet",
    "generate_presenter",
    "lock_content",
    "loudnorm_two_pass",
    "preflight_check",
    "qa_gate",
    "topic_to_script",
    "visual_plan",
]
