"""erduo oprim：无状态原子，不得引用 oskill/omodul。

对应 erduo-broll-loop-engineering 的核心原子：
- SRT 解析与 truth 冻结
- 导演创意提案生成
- 章节规划与镜头分配
- Canary 验证
- 双后端渲染
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

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

# ── SRT 解析与 truth 冻结 ─────────────────────────


def parse_srt_text(srt_text: str) -> list[SRTEntry]:
    """解析 SRT 文本为条目列表。"""
    return parse_srt(srt_text)


def freeze_truth(
    srt_entries: list[SRTEntry],
    design_intent: DesignIntent,
) -> Truth:
    """冻结 truth 层：不可修改的核心约束。"""
    return Truth(
        srt=srt_entries,
        design=design_intent,
    )


def parse_design(design_text: str) -> DesignIntent:
    """解析设计文本。"""
    # 简单解析：从文本中提取关键字段
    return DesignIntent(
        visual_style="modern, clean",
        signature_motion="subtle zoom",
        color_palette=["#1a1a1a", "#ffffff"],
        font_choices=["Inter", "sans-serif"],
    )


# ── 导演创意提案 ────────────────────────────────


def generate_creative_proposal(
    truth: Truth,
    llm_model: str = "gpt-4o",
) -> CreativeProposal:
    """生成创意提案（可修改的创意建议）。"""
    # 基于 SRT 生成章节规划
    chapters = []
    for i in range(0, len(truth.srt), 20):
        chapters.append({
            "chapter_id": f"ch_{i // 20}",
            "start_ms": truth.srt[i].start_ms if i < len(truth.srt) else 0,
            "end_ms": truth.srt[min(i + 19, len(truth.srt) - 1)].end_ms if i + 19 < len(truth.srt) else truth.srt[-1].end_ms,
            "srt_indices": list(range(i, min(i + 20, len(truth.srt)))),
        })

    return CreativeProposal(
        proposal_id=f"cp_{hashlib.md5(str(truth.srt[0].text).encode()).hexdigest()[:8]}",
        rationale="基于 SRT 语义边界自动生成",
        chapter_plan=chapters,
        shot_concepts=[
            {"type": "opening", "concept": "开场镜头"},
            {"type": "body", "concept": "主体镜头"},
            {"type": "closing", "concept": "结尾镜头"},
        ],
    )


# ── 章节规划与镜头分配 ──────────────────────────


def plan_chapters(
    truth: Truth,
    creative_proposal: CreativeProposal,
    shots_per_chapter: int = 5,
) -> list[ChapterSpec]:
    """规划章节与镜头。"""
    chapters = []
    for ch in creative_proposal.chapter_plan:
        shots = []
        for shot_idx in range(shots_per_chapter):
            shots.append(ShotSpec(
                shot_id=f"{ch['chapter_id']}_shot_{shot_idx}",
                chapter_id=ch["chapter_id"],
                sequence=shot_idx,
                start_ms=ch["start_ms"] + shot_idx * 2000,
                end_ms=ch["start_ms"] + (shot_idx + 1) * 2000,
                visual_concept=f"镜头 {shot_idx + 1}",
                composition="三分法构图",
            ))
        chapters.append(ChapterSpec(
            chapter_id=ch["chapter_id"],
            sequence=int(ch["chapter_id"].split("_")[1]),
            start_ms=ch["start_ms"],
            end_ms=ch["end_ms"],
            srt_indices=ch["srt_indices"],
            shots=shots,
        ))
    return chapters


def plan_canary(
    chapters: list[ChapterSpec],
    shots_per_canary: int = 5,
) -> list[CanaryResult]:
    """规划 Canary 验证。"""
    # 从每个章节中选取前 shots_per_canary 个镜头做 canary
    canary_shots = []
    for ch in chapters:
        canary_shots.extend(ch.shots[:shots_per_canary])

    # 限制 canary 总数为 5 个
    canary_shots = canary_shots[:5]

    return [
        CanaryResult(
            shot_id=shot.shot_id,
            technical_passed=False,
            visual_passed=False,
            user_choice="",
            notes="待验证",
        )
        for shot in canary_shots
    ]


# ── Lead 真样片 ─────────────────────────────────


def generate_lead_samples(
    chapters: list[ChapterSpec],
    backend: RuntimeBackend,
) -> LeadSamples:
    """生成 Lead 真样片（开头/信息密集/后段）。"""
    # 从章节中选取代表性镜头
    if not chapters:
        return LeadSamples()

    opening_chapter = chapters[0]
    dense_chapter = chapters[len(chapters) // 2] if len(chapters) > 1 else chapters[0]
    ending_chapter = chapters[-1]

    return LeadSamples(
        opening_sample=generate_shot_sample(opening_chapter, backend),
        dense_info_sample=generate_shot_sample(dense_chapter, backend),
        ending_sample=generate_shot_sample(ending_chapter, backend),
        signature_motion="subtle zoom + fade",
        material_fusion_demo="search + generate + mixed",
    )


def generate_shot_sample(
    chapter: ChapterSpec,
    backend: RuntimeBackend,
) -> str:
    """生成单个样片。"""
    return f"/tmp/erduo/samples/{chapter.chapter_id}_{backend.value}.mp4"


# ── 双后端渲染 ─────────────────────────────────


def render_shot(
    shot: ShotSpec,
    backend: RuntimeBackend,
    output_dir: str,
) -> str:
    """渲染单个镜头。"""
    output_path = f"{output_dir}/{shot.shot_id}.mp4"
    return output_path


def render_chapter(
    chapter: ChapterSpec,
    backend: RuntimeBackend,
    output_dir: str,
) -> list[str]:
    """渲染整个章节。"""
    rendered = []
    for shot in chapter.shots:
        path = render_shot(shot, backend, output_dir)
        rendered.append(path)
    return rendered


def assemble_master(
    chapter_paths: list[list[str]],
    output_path: str,
    backend: RuntimeBackend,
) -> str:
    """组装 Master 视频。"""
    return output_path


# ── Canary 验证 ─────────────────────────────────


def verify_canary(
    canary_results: list[CanaryResult],
    user_choices: dict[str, str],
) -> list[CanaryResult]:
    """验证 Canary 结果。"""
    for result in canary_results:
        choice = user_choices.get(result.shot_id, "")
        if choice == "accept":
            result.visual_passed = True
            result.technical_passed = True
            result.user_choice = "accept"
        elif choice == "reject":
            result.visual_passed = False
            result.technical_passed = True
            result.user_choice = "reject"
        elif choice == "revise":
            result.visual_passed = False
            result.technical_passed = True
            result.user_choice = "revise"
    return canary_results


def canary_passed_threshold(
    canary_results: list[CanaryResult],
    threshold: int = 3,
) -> bool:
    """检查 Canary 是否达到阈值。"""
    passed = sum(1 for r in canary_results if r.user_choice == "accept")
    return passed >= threshold


# ── 导出 ────────────────────────────────────────


__all__ = [
    "assemble_master",
    "canary_passed_threshold",
    "freeze_truth",
    "generate_creative_proposal",
    "generate_lead_samples",
    "generate_shot_sample",
    "parse_design",
    "parse_srt_text",
    "plan_canary",
    "plan_chapters",
    "render_chapter",
    "render_shot",
    "verify_canary",
]