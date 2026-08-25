"""montage 3O 包：OpenMontage 能力内部化。

OpenMontage 是 instruction-driven 视频生产系统：
Agent reads pipeline manifest (YAML) → reads stage director skill (MD)
→ uses tools (Python BaseTool) → self-reviews (meta skill)
→ checkpoints (Python utility) → presents to human for approval

本包将 OpenMontage 的 pipeline-as-instruction 架构转换为 hevi 的 3O 范式：
schemas → oprim → oskill → omodul
"""

from __future__ import annotations

# ── Omodul ──
from hevi.montage.omodul import (
    AVAILABLE_PIPELINES,
    execute_pipeline,
    identify_pipeline,
    plan_delivery,
    plan_full_pipeline,
    plan_reference_analysis,
    plan_stage,
    select_pipeline,
)

# ── Oprim ──
from hevi.montage.oprim import (
    analyze_reference_video,
    apply_playbook_to_compose,
    build_tool_envelope,
    detect_scenes,
    discover_tools,
    estimate_cost,
    extract_transcript,
    load_pipeline_manifest,
    load_playbook,
    provider_menu,
    read_checkpoint,
    reconcile_cost,
    register_tool,
    reserve_cost,
    sample_frames,
    support_envelope,
    update_checkpoint_approval,
    validate_pipeline_manifest,
    write_checkpoint,
)

# ── Oskill ──
from hevi.montage.oskill import (
    checkpoint_approve,
    checkpoint_write,
    pipeline_preflight,
    stage_assets,
    stage_dispatch,
    stage_edit_plan,
    stage_intake,
    stage_mix,
    stage_publish,
    stage_research,
    stage_runtime,
    stage_score,
    stage_script,
    stage_timeline,
    stage_watch,
)

# ── Schemas ──
from hevi.montage.schemas import (
    Artifact,
    ArtifactType,
    CheckpointPolicy,
    CheckpointState,
    CostBudget,
    CostLineItem,
    CostPhase,
    PipelineCategory,
    PipelineManifest,
    PipelineStability,
    PlaybookSchema,
    StageDef,
    ToolCapability,
    ToolContract,
    ToolEnvelope,
    ToolTier,
    VideoAnalysisBrief,
    make_default_checkpoint,
    make_default_cost_budget,
    make_default_pipeline_manifest,
    make_default_tool_contract,
)

__all__ = [
    "AVAILABLE_PIPELINES",
    "Artifact",
    "ArtifactType",
    "CheckpointPolicy",
    "CheckpointState",
    "CostBudget",
    "CostLineItem",
    "CostPhase",
    "PipelineCategory",
    # Schemas
    "PipelineManifest",
    "PipelineStability",
    "PlaybookSchema",
    "StageDef",
    "ToolCapability",
    "ToolContract",
    "ToolEnvelope",
    "ToolTier",
    "VideoAnalysisBrief",
    "analyze_reference_video",
    "apply_playbook_to_compose",
    "build_tool_envelope",
    "checkpoint_approve",
    "checkpoint_write",
    "detect_scenes",
    "discover_tools",
    "estimate_cost",
    "execute_pipeline",
    "extract_transcript",
    # Omodul
    "identify_pipeline",
    # Oprim
    "load_pipeline_manifest",
    "load_playbook",
    "make_default_checkpoint",
    "make_default_cost_budget",
    "make_default_pipeline_manifest",
    "make_default_tool_contract",
    # Oskill
    "pipeline_preflight",
    "plan_delivery",
    "plan_full_pipeline",
    "plan_reference_analysis",
    "plan_stage",
    "provider_menu",
    "read_checkpoint",
    "reconcile_cost",
    "register_tool",
    "reserve_cost",
    "sample_frames",
    "select_pipeline",
    "stage_assets",
    "stage_dispatch",
    "stage_edit_plan",
    "stage_intake",
    "stage_mix",
    "stage_publish",
    "stage_research",
    "stage_runtime",
    "stage_score",
    "stage_script",
    "stage_timeline",
    "stage_watch",
    "support_envelope",
    "update_checkpoint_approval",
    "validate_pipeline_manifest",
    "write_checkpoint",
]