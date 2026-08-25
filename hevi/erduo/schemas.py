"""erduo 3O 包的 schema 契约。

对应 erduo-broll-loop-engineering 的核心模型：
- SRT/Design 输入
- Truth/CreativeProposal 导演意图
- Chapter/Shot/Canary 章节/镜头/验证
- 双后端渲染
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

# ─── 核心枚举 ─────────────────────────────────────


class RuntimeBackend(str, Enum):
    """渲染后端。"""
    HYPERFRAMES = "hyperframes"
    REMOTION = "remotion"
    AUTO = "auto"


class ShotStatus(str, Enum):
    """镜头状态。"""
    PENDING = "pending"
    CAN_PASSED = "can_passed"
    CAN_FAILED = "can_failed"
    RENDERING = "rendering"
    RENDERED = "rendered"
    ACCEPTED = "accepted"
    REVISED = "revised"


class ChapterStatus(str, Enum):
    """章节状态。"""
    PENDING = "pending"
    BUILDING = "building"
    CAN_REVIEW = "can_review"
    APPROVED = "approved"
    RENDERED = "rendered"


# ─── 核心模型 ────────────────────────────────────


class SRTEntry(BaseModel):
    """SRT 字幕条目。"""
    index: int
    start_ms: int
    end_ms: int
    text: str
    speaker: str = ""  # 说话人


class DesignIntent(BaseModel):
    """设计意图。"""
    visual_style: str = ""      # 视觉风格
    signature_motion: str = ""  # 标志性动作
    color_palette: list[str] = Field(default_factory=list)
    font_choices: list[str] = Field(default_factory=list)


class Truth(BaseModel):
    """真相层：不可修改的核心约束。"""
    srt: list[SRTEntry]
    design: DesignIntent
    frozen_at: datetime = Field(default_factory=datetime.utcnow)


class CreativeProposal(BaseModel):
    """创意提案层：可修改的创意建议。"""
    proposal_id: str = ""
    version: int = 1
    rationale: str = ""           # 修改理由
    chapter_plan: list[dict[str, Any]] = Field(default_factory=list)  # 章节规划
    shot_concepts: list[dict[str, Any]] = Field(default_factory=list)  # 镜头概念
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ShotSpec(BaseModel):
    """单镜头规格。"""
    shot_id: str = ""
    chapter_id: str = ""
    sequence: int = 0
    start_ms: int = 0
    end_ms: int = 0
    visual_concept: str = ""
    composition: str = ""
    animation_beats: list[dict[str, Any]] = Field(default_factory=list)
    material_routes: list[str] = Field(default_factory=list)  # search/generate/mixed
    status: ShotStatus = ShotStatus.PENDING
    canary_passed: bool = False
    rendered_path: str = ""


class ChapterSpec(BaseModel):
    """章节规格。"""
    chapter_id: str = ""
    sequence: int = 0
    start_ms: int = 0
    end_ms: int = 0
    srt_indices: list[int] = Field(default_factory=list)
    shots: list[ShotSpec] = Field(default_factory=list)
    status: ChapterStatus = ChapterStatus.PENDING
    canary_results: dict[str, Any] = Field(default_factory=dict)


class LeadSamples(BaseModel):
    """Lead 真样片。"""
    opening_sample: str = ""      # 开头样片
    dense_info_sample: str = ""   # 信息密集段样片
    ending_sample: str = ""       # 后段样片
    signature_motion: str = ""    # 标志性动作演示
    material_fusion_demo: str = ""  # 素材融合演示


class CanaryResult(BaseModel):
    """Canary 验证结果。"""
    shot_id: str = ""
    technical_passed: bool = False
    visual_passed: bool = False
    user_choice: str = ""  # "accept" / "reject" / "revise"
    notes: str = ""


class ProductionJob(BaseModel):
    """完整生产作业。"""
    job_id: str = Field(default_factory=lambda: f"erduo-{__import__('uuid').uuid4().hex[:12]}")
    user_id: str = ""
    srt_path: str = ""
    design_path: str = ""
    truth: Truth | None = None
    creative_proposal: CreativeProposal = Field(default_factory=CreativeProposal)
    chapters: list[ChapterSpec] = Field(default_factory=list)
    lead_samples: LeadSamples = Field(default_factory=LeadSamples)
    canary_results: list[CanaryResult] = Field(default_factory=list)
    backend: RuntimeBackend = RuntimeBackend.HYPERFRAMES
    status: str = "pending"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# ─── 工厂函数 ────────────────────────────────────


def make_production_job(
    srt_path: str,
    design_path: str,
    backend: RuntimeBackend = RuntimeBackend.HYPERFRAMES,
    user_id: str = "",
) -> ProductionJob:
    """创建生产作业。"""
    return ProductionJob(
        srt_path=srt_path,
        design_path=design_path,
        backend=backend,
        user_id=user_id,
    )


def parse_srt(srt_text: str) -> list[SRTEntry]:
    """解析 SRT 文本为条目列表。"""
    entries = []
    blocks = srt_text.strip().split("\n\n")
    for block in blocks:
        lines = block.strip().split("\n")
        if len(lines) >= 3:
            index = int(lines[0])
            time_line = lines[1]
            text = "\n".join(lines[2:])
            start_str, end_str = time_line.split(" --> ")
            start_ms = _time_to_ms(start_str)
            end_ms = _time_to_ms(end_str)
            entries.append(SRTEntry(
                index=index,
                start_ms=start_ms,
                end_ms=end_ms,
                text=text,
            ))
    return entries


def _time_to_ms(time_str: str) -> int:
    """将 SRT 时间格式转换为毫秒。"""
    time_part, ms_part = time_str.split(",")
    h, m, s = map(int, time_part.split(":"))
    return ((h * 3600 + m * 60 + s) * 1000) + int(ms_part)


# ─── 导出 ────────────────────────────────────────


__all__ = [
    "CanaryResult",
    "ChapterSpec",
    "ChapterStatus",
    "CreativeProposal",
    "DesignIntent",
    "LeadSamples",
    "ProductionJob",
    "RuntimeBackend",
    "SRTEntry",
    "ShotSpec",
    "ShotStatus",
    "Truth",
    "make_production_job",
    "parse_srt",
]
