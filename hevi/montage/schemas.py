"""montage 3O 包的 schema 契约。

OpenMontage 能力内部化：Pipeline/Stage/Tool/Artifact/Playbook 契约。
对齐 OpenMontage 的 instruction-driven 架构。
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# ─── Pipeline Manifest ──────────────────────────────


class PipelineCategory(str, Enum):
    """Pipeline 类别。"""
    GENERATED = "generated"
    FOOTAGE_BASED = "footage_based"
    SCREEN_RECORDING = "screen_recording"
    SHORT_FORM = "short_form"
    PODCAST = "podcast"
    CINEMATIC = "cinematic"
    ANIMATION = "animation"
    CHARACTER = "character"
    HYBRID = "hybrid"
    AVATAR = "avatar"
    LOCALIZATION = "localization"
    TEST = "test"


class PipelineStability(str, Enum):
    PRODUCTION = "production"
    BETA = "beta"
    EXPERIMENTAL = "experimental"


class CheckpointPolicy(str, Enum):
    GUIDED = "guided"
    AUTO = "auto"
    MANUAL = "manual"


class PipelineManifest(BaseModel):
    """Pipeline 清单契约。对应 OpenMontage pipeline_defs/*.yaml"""
    model_config = ConfigDict(extra="allow")

    name: str
    version: str = "1.0"
    description: str = ""
    category: PipelineCategory = PipelineCategory.GENERATED
    stability: PipelineStability = PipelineStability.PRODUCTION

    default_checkpoint_policy: CheckpointPolicy = CheckpointPolicy.GUIDED

    # Reference video input
    reference_input_supported: bool = True
    reference_analysis_depth: str = "standard"
    reference_analysis_tools: list[str] = Field(default_factory=list)

    # Extensions
    extensions_custom_scripts: bool = True
    extensions_custom_playbooks: bool = True
    extensions_custom_skills: bool = True
    extensions_custom_tools: bool = False

    # Required skills (meta + pipeline stage directors)
    required_skills: list[str] = Field(default_factory=list)

    # Orchestration
    orchestration_mode: str = "executive-producer"
    orchestration_skill: str = ""
    budget_default_usd: float = 2.0
    max_revisions_per_stage: int = 3
    max_send_backs: int = 3
    max_wall_time_minutes: int = 20

    # Compatible playbooks
    compatible_playbooks_recommended: list[str] = Field(default_factory=list)
    compatible_playbooks_also_works: list[str] = Field(default_factory=list)
    compatible_playbooks_custom_allowed: bool = True

    # Stages
    stages: list[StageDef] = Field(default_factory=list)


class StageDef(BaseModel):
    """单阶段定义。"""
    model_config = ConfigDict(extra="allow")

    name: str
    skill: str
    produces: list[str] = Field(default_factory=list)
    required_artifacts_in: list[str] = Field(default_factory=list)
    optional_artifacts_in: list[str] = Field(default_factory=list)
    required_tools: list[str] = Field(default_factory=list)
    optional_tools: list[str] = Field(default_factory=list)
    tools_available: list[str] = Field(default_factory=list)
    checkpoint_required: bool = False
    human_approval_default: bool = False
    review_focus: list[str] = Field(default_factory=list)
    success_criteria: list[str] = Field(default_factory=list)
    sub_stages: list[dict[str, Any]] = Field(default_factory=list)


# ─── Tool Contract ──────────────────────────────────


class ToolTier(str, Enum):
    CORE = "core"
    STANDARD = "standard"
    PREMIUM = "premium"
    LOCAL = "local"


class ToolCapability(str, Enum):
    TTS = "tts"
    IMAGE_GEN = "image_gen"
    VIDEO_GEN = "video_gen"
    MUSIC_GEN = "music_gen"
    VIDEO_COMPOSE = "video_compose"
    VIDEO_STITCH = "video_stitch"
    VIDEO_TRIM = "video_trim"
    STOCK_VIDEO = "stock_video"
    STOCK_IMAGE = "stock_image"
    SUBTITLE = "subtitle"
    AUDIO_MIX = "audio_mix"
    VIDEO_ANALYZE = "video_analyze"
    RESEARCH = "research"
    SCRIPT = "script"
    EDIT_PLAN = "edit_plan"
    DELIVERY = "delivery"
    PUBLISH = "publish"
    ENHANCEMENT = "enhancement"
    CHARACTER_ANIM = "character_anim"
    GRAPHICS_3D = "graphics_3d"
    AVATAR = "avatar"


class ToolContract(BaseModel):
    """工具契约。对应 OpenMontage BaseTool contract。"""
    model_config = ConfigDict(extra="allow")

    name: str
    version: str = "1.0"
    tier: ToolTier = ToolTier.STANDARD
    capability: ToolCapability
    provider: str = ""
    summary: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    cost_per_unit_usd: float = 0.0
    unit: str = "call"
    latency_estimate_s: float = 5.0
    reliability_score: float = 0.9
    supports: list[str] = Field(default_factory=list)
    fallback_tools: list[str] = Field(default_factory=list)
    agent_skills: list[str] = Field(default_factory=list)


class ToolEnvelope(BaseModel):
    """能力信封：当前环境可用工具的概览。"""
    capabilities: dict[str, list[str]] = Field(default_factory=dict)  # capability -> [tool_names]
    providers: dict[str, list[str]] = Field(default_factory=dict)  # capability -> [providers]
    total_tools: int = 0


# ─── Cost Tracking ──────────────────────────────────


class CostPhase(str, Enum):
    ESTIMATE = "estimate"
    RESERVE = "reserve"
    RECONCILE = "reconcile"


class CostLineItem(BaseModel):
    """成本明细项。"""
    tool_name: str
    provider: str
    capability: str
    estimated_units: float = 1.0
    cost_per_unit_usd: float = 0.0
    estimated_cost_usd: float = 0.0
    actual_units: float = 0.0
    actual_cost_usd: float = 0.0
    phase: CostPhase = CostPhase.ESTIMATE


class CostBudget(BaseModel):
    """成本预算。"""
    budget_usd: float = 2.0
    spent_usd: float = 0.0
    reserved_usd: float = 0.0
    line_items: list[CostLineItem] = Field(default_factory=list)

    def remaining(self) -> float:
        return self.budget_usd - self.reserved_usd - self.spent_usd


# ─── Artifact Schemas ───────────────────────────────


class ArtifactType(str, Enum):
    RESEARCH_BRIEF = "research_brief"
    PROPOSAL_PACKET = "proposal_packet"
    DECISION_LOG = "decision_log"
    SCRIPT = "script"
    SCENE_PLAN = "scene_plan"
    ASSET_MANIFEST = "asset_manifest"
    EDIT_DECISIONS = "edit_decisions"
    RENDER_REPORT = "render_report"
    FINAL_REVIEW = "final_review"
    PUBLISH_LOG = "publish_log"
    VIDEO_ANALYSIS_BRIEF = "video_analysis_brief"
    CHECKPOINT = "checkpoint"


class Artifact(BaseModel):
    """标准产物。"""
    model_config = ConfigDict(extra="allow")

    type: ArtifactType
    pipeline: str
    stage: str
    data: dict[str, Any] = Field(default_factory=dict)
    schema_version: str = "1.0"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    approved: bool = False
    approved_at: datetime | None = None
    review_notes: str = ""


# ─── Reference Video Analysis ───────────────────────


class VideoAnalysisBrief(BaseModel):
    """参考视频分析摘要。"""
    model_config = ConfigDict(extra="allow")

    source_url: str = ""
    content: str = ""
    pacing: str = ""
    structure: str = ""
    style: str = ""
    what_makes_it_work: list[str] = Field(default_factory=list)
    concepts: list[dict[str, Any]] = Field(default_factory=list)
    duration_s: float = 0.0
    hook_analysis: str = ""
    scene_count: int = 0
    shot_types: list[str] = Field(default_factory=list)


# ─── Playbook ───────────────────────────────────────


class PlaybookSchema(BaseModel):
    """风格手册。对应 OpenMontage styles/*.yaml。"""
    model_config = ConfigDict(extra="allow")

    name: str
    version: str = "1.0"
    category: str = "explainer"
    # Design tokens
    chart_palette: list[str] = Field(default_factory=list)
    scale_system: list[float] = Field(default_factory=list)
    weight_matrix: dict[str, float] = Field(default_factory=dict)
    color_rules: dict[str, str] = Field(default_factory=dict)
    # Visual language
    typography: dict[str, Any] = Field(default_factory=dict)
    motion: dict[str, Any] = Field(default_factory=dict)
    audio: dict[str, Any] = Field(default_factory=dict)
    # Asset generation constraints
    asset_constraints: dict[str, Any] = Field(default_factory=dict)
    # Runtime mapping
    preferred_runtime: str = "remotion"


# ─── Checkpoint ─────────────────────────────────────


class CheckpointState(BaseModel):
    """检查点状态。"""
    model_config = ConfigDict(extra="allow")

    pipeline: str
    stage: str
    artifacts: dict[str, Artifact] = Field(default_factory=dict)
    tool_results: dict[str, Any] = Field(default_factory=dict)
    cost_state: CostBudget | None = None
    human_approval: str = "pending"  # pending | approved | approved_with_changes | rejected
    review_notes: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# ─── Factory ────────────────────────────────────────


def make_default_pipeline_manifest(name: str) -> PipelineManifest:
    return PipelineManifest(name=name)


def make_default_tool_contract(name: str, capability: ToolCapability) -> ToolContract:
    return ToolContract(name=name, capability=capability)


def make_default_cost_budget(budget_usd: float = 2.0) -> CostBudget:
    return CostBudget(budget_usd=budget_usd)


def make_default_checkpoint(pipeline: str, stage: str) -> CheckpointState:
    return CheckpointState(pipeline=pipeline, stage=stage)