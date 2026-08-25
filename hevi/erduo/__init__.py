"""erduo 3O 包：B-roll循环工程。

erduo-broll-loop-engineering 核心能力内部化：
SRT 解析 → Truth 冻结 → 创意提案 → 章节规划 → Canary 验证 → 双后端渲染 → Master 组装
"""

from __future__ import annotations

# ── Omodul ──
from hevi.erduo.omodul import (
    execute_erduo_pipeline,
    plan_erduo_pipeline,
    plan_full_erduo_pipeline,
)

# ── Oprim ──
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

# ── Oskill ──
from hevi.erduo.oskill import (
    skill_assemble_master,
    skill_build_chapters,
    skill_canary_threshold,
    skill_canary_verify,
    skill_full_production,
    skill_generate_lead_samples,
    skill_render_chapters,
)

# ── Schemas ──
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

__all__ = [
    "CanaryResult",
    "ChapterSpec",
    "ChapterStatus",
    "CreativeProposal",
    "DesignIntent",
    "LeadSamples",
    "ProductionJob",
    # Schemas
    "RuntimeBackend",
    "SRTEntry",
    "ShotSpec",
    "ShotStatus",
    "Truth",
    "assemble_master",
    "canary_passed_threshold",
    "execute_erduo_pipeline",
    "freeze_truth",
    "generate_creative_proposal",
    "generate_lead_samples",
    "generate_shot_sample",
    "make_production_job",
    "parse_design",
    "parse_srt",
    # Oprim
    "parse_srt_text",
    "plan_canary",
    "plan_chapters",
    # Omodul
    "plan_erduo_pipeline",
    "plan_full_erduo_pipeline",
    "render_chapter",
    "render_shot",
    "skill_assemble_master",
    "skill_build_chapters",
    "skill_canary_threshold",
    "skill_canary_verify",
    # Oskill
    "skill_full_production",
    "skill_generate_lead_samples",
    "skill_render_chapters",
    "verify_canary",
]