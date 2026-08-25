"""digital_human omodul:文本规划/任务编排，供 studio/production 工作流调用。

对应 lanshu SKILL.md 的状态机驱动：
intake → content_locked → audio_locked → visual_plan_locked → presenter_generated → composition_checked → rendered → verified
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from hevi.digital_human.oskill import (
    caption_plan,
    content_lock,
    delivery,
    generate_presenter,
    preflight_check,
    qa_gate,
    visual_plan,
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

# ─── 作业初始化 ─────────────────────────────────────


def init_job(
    job_dir: str,
    presenter_image: str,
    topic: str = "",
    script_path: str = "",
    voice_sample: str = "",
    supporting_media: list[str] | None = None,
    rights_confirmed: bool = False,
    adult_presenter_confirmed: bool = False,
    remote_upload_approved: bool = False,
    voice_clone_approved: bool = False,
    language: str = "auto",
    audience: str = "general",
    duration_target_s: int = 60,
    aspect: str = "9:16",
    width: int = 1080,
    height: int = 1920,
    fps: int = 30,
    style: str = "credible contemporary presenter",
    watermark: str = "",
    cta: str = "",
) -> PresenterJob:
    """初始化作业（对应 lanshu init_job.py）。

    创建作业目录结构和 job.json，返回 PresenterJob 实例。
    """
    job = make_default_job()
    job.job_id = Path(job_dir).name
    job.topic = topic
    job.script_path = script_path
    job.presenter_image = presenter_image
    job.voice_sample = voice_sample
    job.supporting_media = supporting_media or []
    job.rights_confirmed = rights_confirmed
    job.adult_presenter_confirmed = adult_presenter_confirmed
    job.remote_upload_approved = remote_upload_approved
    job.voice_clone_approved = voice_clone_approved
    job.language = language
    job.audience = audience
    job.duration_target_s = duration_target_s
    job.aspect = aspect
    job.width = width
    job.height = height
    job.fps = fps
    job.style = style
    job.watermark = watermark
    job.cta = cta

    # 创建目录结构
    dirs = [
        "docs",
        "assets/source",
        "assets/audio/reference",
        "assets/audio/raw",
        "assets/audio/final",
        "assets/video/candidates",
        "assets/video/selected",
        "assets/video/render",
        "assets/captions",
        "qa/requests",
        "qa/asr",
        "qa/contacts",
        "qa/reports",
        "renders",
        "outputs",
    ]
    for d in dirs:
        (Path(job_dir) / d).mkdir(parents=True, exist_ok=True)

    # 保存 job.json
    job_path = Path(job_dir) / "job.json"
    job_path.write_text(job.model_dump_json(indent=2, ensure_ascii=False), encoding="utf-8")

    return job


# ─── 阶段计划构建 ────────────────────────────────────


def plan_generation(job: PresenterJob) -> dict[str, Any]:
    """构建生成阶段计划 (intake → audio_locked)。

    对应 lanshu generation.md 的完整流程
    """
    # 预检
    preflight = preflight_check(job)

    plan = {
        "phase": "generation",
        "job_id": job.job_id,
        "current_status": job.status.value,
        "target_status": JobStatus.AUDIO_LOCKED.value,
        "preflight": preflight.model_dump(),
        "steps": [
            {
                "step": "lock_content",
                "fn": "content_lock",
                "args": {"voice_id": job.voice_id, "rate": job.rate},
                "required": True,
            },
            {
                "step": "generate_narration",
                "fn": "generate_narration",
                "args": {},
                "required": True,
            },
            {
                "step": "calibrate_loudness",
                "fn": "calibrate_audio_loudness",
                "args": {"target_lufs": job.program_lufs},
                "required": True,
            },
        ],
        "gate": {
            "type": "qa_gate",
            "checks": [
                "rights_confirmed",
                "adult_presenter_confirmed",
                "remote_upload_approved",
                "voice_clone_approved",
                "script_not_empty",
                "final_audio_exists",
            ],
        },
    }

    return plan


def plan_visual(job: PresenterJob, narration_duration_s: float) -> dict[str, Any]:
    """构建视觉规划阶段计划 (audio_locked → visual_plan_locked)。

    对应 lanshu editing.md 的视觉路线选择 + 时间轴构建
    """
    plan = {
        "phase": "visual_plan",
        "job_id": job.job_id,
        "current_status": job.status.value,
        "target_status": JobStatus.VISUAL_PLAN_LOCKED.value,
        "steps": [
            {
                "step": "visual_plan",
                "fn": "visual_plan",
                "args": {
                    "narration_duration_s": narration_duration_s,
                    "opening_target_s": 4.0,
                    "closing_target_s": 5.0,
                },
                "required": True,
            },
            {
                "step": "caption_plan",
                "fn": "caption_plan",
                "args": {
                    "audio_duration_s": narration_duration_s,
                    "keyword_anchors": None,
                },
                "required": True,
            },
        ],
        "gate": {
            "type": "qa_gate",
            "checks": [
                "timeline_valid",
                "caption_plan_valid",
            ],
        },
    }

    return plan


def plan_presenter_generation(job: PresenterJob) -> dict[str, Any]:
    """构建人物生成阶段计划 (visual_plan_locked → presenter_generated)。

    对应 lanshu generation.md 第 2 节：试片 → 全片
    """
    plan = {
        "phase": "presenter_generation",
        "job_id": job.job_id,
        "current_status": job.status.value,
        "target_status": JobStatus.PRESENTER_GENERATED.value,
        "steps": [
            {
                "step": "pilot_generation",
                "fn": "generate_presenter",
                "args": {"mode": "pilot", "pilot_duration_s": 5.0},
                "required": True,
            },
            {
                "step": "pilot_qa",
                "fn": "qa_gate",
                "args": {
                    "identity_coherent": True,
                    "mouth_sync": True,
                    "no_black_frames": True,
                    "captions_readable": True,
                    "safe_zones_ok": True,
                },
                "required": True,
            },
            {
                "step": "full_generation",
                "fn": "generate_presenter",
                "args": {"mode": "full"},
                "required": True,
            },
        ],
        "gate": {
            "type": "qa_gate",
            "checks": [
                "pilot_accepted",
                "identity_stable",
                "mouth_timing_ok",
            ],
        },
    }

    return plan


def plan_composition(job: PresenterJob) -> dict[str, Any]:
    """构建合成/剪辑阶段计划 (presenter_generated → composition_checked)。

    对应 lanshu editing.md 第 3-4 节：时间轴合成 + 字幕/动效烧录
    """
    plan = {
        "phase": "composition",
        "job_id": job.job_id,
        "current_status": job.status.value,
        "target_status": JobStatus.COMPOSITION_CHECKED.value,
        "steps": [
            {
                "step": "compose_timeline",
                "fn": "compose_timeline",
                "args": {},
                "required": True,
            },
            {
                "step": "burn_captions",
                "fn": "burn_captions",
                "args": {},
                "required": True,
            },
            {
                "step": "add_keyword_effects",
                "fn": "add_keyword_effects",
                "args": {},
                "required": True,
            },
            {
                "step": "composition_qa",
                "fn": "qa_gate",
                "args": {
                    "identity_coherent": True,
                    "mouth_sync": True,
                    "no_black_frames": True,
                    "no_overlay": True,
                    "captions_readable": True,
                    "safe_zones_ok": True,
                },
                "required": True,
            },
        ],
        "gate": {
            "type": "qa_gate",
            "checks": [
                "no_flash",
                "no_duplicate_presenter",
                "no_source_time_reset",
                "no_missing_overlay",
                "no_face_obstruction",
                "no_caption_collision",
                "ui_readable",
            ],
        },
    }

    return plan


def plan_delivery(job: PresenterJob, render_path: str, output_dir: str, stem: str = "presenter-video") -> dict[str, Any]:
    """构建交付阶段计划 (composition_checked → verified)。

    对应 lanshu finalize_delivery.sh
    """
    plan = {
        "phase": "delivery",
        "job_id": job.job_id,
        "current_status": job.status.value,
        "target_status": JobStatus.VERIFIED.value,
        "steps": [
            {
                "step": "render_master",
                "fn": "delivery",
                "args": {
                    "render_path": render_path,
                    "output_dir": output_dir,
                    "stem": stem,
                },
                "required": True,
            },
            {
                "step": "final_qa",
                "fn": "qa_gate",
                "args": {
                    "identity_coherent": True,
                    "mouth_sync": True,
                    "no_black_frames": True,
                    "captions_readable": True,
                    "safe_zones_ok": True,
                },
                "required": True,
            },
        ],
        "gate": {
            "type": "qa_gate",
            "checks": [
                "master_decode_ok",
                "share_decode_ok",
                "loudness_in_spec",
                "contact_sheet_complete",
                "visual_review_passed",
            ],
        },
    }

    return plan


# ─── 完整作业计划 ────────────────────────────────────


def build_full_job_plan(
    job: PresenterJob,
    narration_duration_s: float,
    render_path: str,
    output_dir: str,
    stem: str = "presenter-video",
) -> dict[str, Any]:
    """构建完整的端到端作业计划。

    供 production workflow 调用，一次性生成全阶段计划。
    """
    return {
        "job_id": job.job_id,
        "created_at": datetime.utcnow().isoformat(),
        "phases": [
            plan_generation(job),
            plan_visual(job, narration_duration_s),
            plan_presenter_generation(job),
            plan_composition(job),
            plan_delivery(job, render_path, output_dir, stem),
        ],
        "state_machine": [
            "intake",
            "content_locked",
            "audio_locked",
            "visual_plan_locked",
            "presenter_generated",
            "composition_checked",
            "rendered",
            "verified",
        ],
        "current_state": job.status.value,
    }


# ─── 执行器 ─────────────────────────────────────────


async def execute_plan(job: PresenterJob, plan: dict[str, Any]) -> dict[str, Any]:
    """执行计划的各个阶段（由 workflow 调用）。"""
    results: dict[str, Any] = {"job_id": job.job_id, "phases": []}

    for phase_plan in plan.get("phases", []):
        phase_result = await _execute_phase(job, phase_plan)
        results["phases"].append(phase_result)

        # 更新作业状态
        job.status = JobStatus(phase_plan["target_status"])

    return results


async def _execute_phase(job: PresenterJob, phase_plan: dict[str, Any]) -> dict[str, Any]:
    """执行单个阶段（占位实现）。"""
    phase_name = phase_plan.get("phase", "unknown")
    results = {"phase": phase_name, "steps": []}

    for step in phase_plan.get("steps", []):
        step_result = {"step": step["step"], "ok": True}
        results["steps"].append(step_result)

    return results


# ─── 导出 ───────────────────────────────────────────

__all__ = [
    "build_full_job_plan",
    "execute_plan",
    "init_job",
    "plan_composition",
    "plan_delivery",
    "plan_generation",
    "plan_presenter_generation",
    "plan_visual",
]
