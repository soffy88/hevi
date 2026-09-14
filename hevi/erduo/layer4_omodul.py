"""erduo omodul：文本规划/任务编排，供 studio/production 工作流调用。

对应 erduo-broll-loop-engineering 的 stage-by-stage 规划与执行
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from hevi.erduo.oprim import (
    assemble_master,
    canary_passed_threshold,
    freeze_truth,
    generate_creative_proposal,
    generate_lead_samples,
    generate_shot_sample,
    parse_design,
    parse_srt_text,
    plan_canary,
    plan_chapters,
    render_chapter,
    render_shot,
    verify_canary,
)
from hevi.erduo.oskill import (
    skill_assemble_master,
    skill_build_chapters,
    skill_canary_threshold,
    skill_canary_verify,
    skill_full_production,
    skill_generate_lead_samples,
    skill_render_chapters,
)
from hevi.erduo.schemas import (
    ProductionJob,
    RuntimeBackend,
    make_production_job,
)

# ── Pipeline 规划 ─────────────────────────────────────


def plan_erduo_pipeline(
    srt_path: str,
    design_path: str,
    user_id: str = "",
    backend: str = "hyperframes",
    target_clips: int | None = None,
) -> dict[str, Any]:
    """规划完整的 erduo Clip Generator pipeline。

    对应 erduo-broll-loop-engineering 的完整 pipeline。
    """
    import uuid
    f"tasks/{uuid.uuid4().hex[:8]}"
    runtime_backend = RuntimeBackend(backend)
    make_production_job(
        srt_path=srt_path,
        design_path=design_path,
        backend=runtime_backend,
        user_id=user_id,
    )

    return {
        "pipeline": "erduo-clip-generator",
        "input": {"srt_path": srt_path, "design_path": design_path},
        "user_id": user_id,
        "backend": backend,
        "target_clips": target_clips or 5,
        "checkpoint_policy": "after_every_stage",
        "stages": [
            {"stage": "acquire_video", "desc": "下载并提取音频"},
            {"stage": "transcribe", "desc": "语音识别生成 SRT"},
            {"stage": "segment", "desc": "LLM 智能分割"},
            {"stage": "translate", "desc": "专业翻译 + 双语字幕"},
            {"stage": "tts", "desc": "TTS 配音 + video_with_tts.mp4"},
            {"stage": "render", "desc": "横竖屏渲染"},
            {"stage": "cover", "desc": "平台封面生成"},
        ],
        "estimated_cost_usd": 3.0,
        "stages_plan": [
            {"stage": "acquire_video", "desc": "下载并提取音频"},
            {"stage": "transcribe", "desc": "语音识别生成 SRT"},
            {"stage": "segment", "desc": "LLM 智能分割"},
            {"stage": "translate", "desc": "专业翻译 + 双语字幕"},
            {"stage": "tts", "desc": "TTS 配音 + video_with_tts.mp4"},
            {"stage": "render", "desc": "横竖屏渲染"},
            {"stage": "cover", "desc": "平台封面生成"},
        ],
    }


def plan_full_erduo_pipeline(
    srt_path: str,
    design_path: str,
    user_id: str = "",
    backend: str = "hyperframes",
) -> dict[str, Any]:
    """规划完整的 erduo pipeline（7个stage）。"""
    return plan_erduo_pipeline(srt_path=srt_path, design_path=design_path, user_id=user_id, backend=backend)


# ── 执行器 ─────────────────────────────────────────


async def execute_erduo_pipeline(
    srt_path: str,
    design_path: str,
    user_id: str = "",
    backend: str = "hyperframes",
) -> dict[str, Any]:
    """执行完整的 erduo pipeline（由 hevi studio pipeline 调用）。"""
    runtime_backend = RuntimeBackend(backend)
    job = make_production_job(
        srt_path=srt_path,
        design_path=design_path,
        backend=runtime_backend,
        user_id=user_id,
    )

    # Stage 1: SRT 解析 + Truth 冻结
    srt_text = Path(srt_path).read_text(encoding="utf-8")
    srt_entries = parse_srt_text(srt_text)
    design_text = Path(design_path).read_text(encoding="utf-8")
    design_intent = parse_design(design_text)
    truth = freeze_truth(srt_entries, design_intent)
    job.truth = truth

    # Stage 2: 创意提案
    creative_proposal = generate_creative_proposal(truth)
    job.creative_proposal = creative_proposal

    # Stage 3: 章节规划
    chapters = plan_chapters(truth, creative_proposal)
    job.chapters = chapters

    # Stage 3: Canary 规划
    canary_results = plan_canary(chapters)
    job.canary_results = canary_results

    # Stage 4: Lead 真样片
    lead_samples = generate_lead_samples(chapters, runtime_backend)
    job.lead_samples = lead_samples

    # Stage 5: 渲染章节
    for chapter in job.chapters:
        for shot in chapter.shots:
            shot.rendered_path = render_shot(
                shot, runtime_backend, f"/tmp/erduo/{job.job_id}"
            )

    # Stage 6: 组装 Master
    chapter_paths = []
    for chapter in job.chapters:
        paths = [shot.rendered_path for shot in chapter.shots]
        chapter_paths.append(paths)

    master_path = assemble_master(
        chapter_paths, f"/tmp/erduo/{job.job_id}/master.mp4", runtime_backend
    )

    job.status = "completed"

    return {
        "job_id": job.job_id,
        "stages_completed": 6,
        "final_status": job.status,
        "outputs": {
            "master_path": master_path,
            "chapters": [c.chapter_id for c in job.chapters],
            "lead_samples": [job.lead_samples.opening_sample, job.lead_samples.dense_info_sample, job.lead_samples.ending_sample],
            "rendered_shots": [s.shot_id for c in job.chapters for s in c.shots],
        },
    }


# ── 导出 ───────────────────────────────────────────

__all__ = [
    "execute_erduo_pipeline",
    "plan_erduo_pipeline",
]
