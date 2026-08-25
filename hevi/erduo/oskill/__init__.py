"""erduo oskill：组合 ≥2 个 oprim 原子，不得引用 omodul。

对应 erduo-broll-loop-engineering 的技能组合。
"""

from __future__ import annotations

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
from hevi.erduo.schemas import (
    CanaryResult,
    ChapterSpec,
    ChapterStatus,
    CreativeProposal,
    DesignIntent,
    LeadSamples,
    ProductionJob,
    RuntimeBackend,
    ShotSpec,
    ShotStatus,
    SRTEntry,
    Truth,
    make_production_job,
    parse_srt,
)

# ── 技能 1: 完整生产流程 ─────────────────────────────


def skill_full_production(
    srt_path: str,
    design_path: str,
    backend: RuntimeBackend = RuntimeBackend.HYPERFRAMES,
    user_id: str = "",
) -> ProductionJob:
    """完整生产技能：SRT 解析 → Truth 冻结 → 创意提案 → 章节规划 → Canary → 渲染 → 组装。"""
    # 1. 解析 SRT
    srt_text = Path(srt_path).read_text(encoding="utf-8")
    srt_entries = parse_srt_text(srt_text)

    # 2. 解析设计
    design_text = Path(design_path).read_text(encoding="utf-8")
    design_intent = parse_design(design_text)

    # 3. 冻结 Truth
    truth = freeze_truth(srt_entries, design_intent)

    # 4. 创建作业
    job = make_production_job(srt_path, design_path, backend, user_id)
    job.truth = truth

    # 5. 生成创意提案
    creative_proposal = generate_creative_proposal(truth)
    job.creative_proposal = creative_proposal

    # 6. 规划章节
    chapters = plan_chapters(truth, creative_proposal)
    job.chapters = chapters

    # 6. 规划 Canary
    canary_results = plan_canary(chapters)
    job.canary_results = canary_results

    # 7. 生成 Lead 真样片
    lead_samples = generate_lead_samples(chapters, backend)
    job.lead_samples = lead_samples

    return job


# ── 技能 2: 章节构建 ────────────────────────────────


def skill_build_chapters(
    job: ProductionJob,
    shots_per_chapter: int = 5,
) -> ProductionJob:
    """章节构建技能：根据创意提案规划章节与镜头。"""
    if job.truth is None:
        raise ValueError("truth must be frozen before chapter planning")
    if job.truth is None:
        raise ValueError("truth must be frozen before chapter planning")
    chapters = plan_chapters(job.truth, job.creative_proposal, shots_per_chapter)
    job.chapters = chapters
    return job


# ── 技能 3: Canary 验证 ─────────────────────────────


def skill_canary_verify(
    job: ProductionJob,
    user_choices: dict[str, str],
) -> ProductionJob:
    """Canary 验证技能：用户选择接受/拒绝/修改。"""
    job.canary_results = verify_canary(job.canary_results, user_choices)
    return job


def skill_canary_threshold(
    job: ProductionJob,
    threshold: int = 3,
) -> bool:
    """检查 Canary 是否通过阈值。"""
    return canary_passed_threshold(job.canary_results, threshold)


# ── 技能 4: 双后端渲染 ─────────────────────────────


def skill_render_chapters(
    job: ProductionJob,
    output_dir: str,
) -> ProductionJob:
    """双后端渲染技能：渲染所有章节。"""
    for chapter in job.chapters:
        render_chapter(chapter, job.backend, output_dir)
    return job


# ── 技能 5: Master 组装 ────────────────────────────


def skill_assemble_master(
    job: ProductionJob,
    output_path: str,
    output_dir: str,
) -> str:
    """组装 Master 视频。"""
    chapter_paths = []
    for chapter in job.chapters:
        paths = [f"{output_dir}/{shot.shot_id}.mp4" for shot in chapter.shots]
        chapter_paths.append(paths)

    return assemble_master(chapter_paths, output_path, job.backend)


# ── 技能 6: Lead 真样片生成 ────────────────────────


def skill_generate_lead_samples(
    job: ProductionJob,
) -> ProductionJob:
    """生成 Lead 真样片技能。"""
    job.lead_samples = generate_lead_samples(job.chapters, job.backend)
    return job


# ── 导出 ───────────────────────────────────────────

__all__ = [
    "skill_assemble_master",
    "skill_build_chapters",
    "skill_canary_threshold",
    "skill_canary_verify",
    "skill_full_production",
    "skill_generate_lead_samples",
    "skill_render_chapters",
]
