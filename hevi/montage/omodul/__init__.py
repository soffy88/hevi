"""montage omodul：文本规划/任务编排，供 studio/production 工作流调用。

对应 OpenMontage 的 AGENT_GUIDE.md 工作流：
1. Identify pipeline → 2. Read manifest → 3. Preflight → 4. Execute stage-by-stage → 5. Checkpoint → 6. Human approval
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from hevi.montage.omodul.agentic import AgenticMontageConfig, agentic_montage_workflow
from hevi.montage.omodul.video_agent import (
    VideoEvidenceConfig,
    compute_video_agent_fingerprint,
    video_agent_transaction,
    video_evidence_index,
    video_evidence_search,
    video_script_from_transcript,
)
from hevi.montage.oprim import (
    analyze_reference_video,
    apply_playbook_to_compose,
    build_tool_envelope,
    detect_scenes,
    discover_tools,
    extract_transcript,
    load_pipeline_manifest,
    load_playbook,
    provider_menu,
    read_checkpoint,
    sample_frames,
    support_envelope,
    update_checkpoint_approval,
    validate_pipeline_manifest,
    write_checkpoint,
)
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
from hevi.montage.schemas import (
    Artifact,
    ArtifactType,
    CheckpointState,
    CostBudget,
    PipelineManifest,
    StageDef,
    ToolContract,
    VideoAnalysisBrief,
    make_default_checkpoint,
    make_default_cost_budget,
    make_default_pipeline_manifest,
)

# ─── Pipeline Selection & Planning ──────────────────


AVAILABLE_PIPELINES = {
    "animated-explainer": "AI 生成式讲解视频（研究→脚本→场景→素材→剪辑→合成→发布）",
    "animation": "动画优先：动效、动态排版、抽象概念可视化",
    "avatar-spokesperson": "数字人发言人视频",
    "character-animation": "本地绑定角色动画（SVG rig、pose library、HyperFrames）",
    "cinematic": "电影感预告片、品牌片、情绪驱动剪辑",
    "clip-factory": "长内容批量切片→短视频",
    "documentary-montage": "纪录片式蒙太奇：从免费开放素材库语义检索→剪辑",
    "hybrid": "源素材 + AI 生成辅助视觉",
    "localization-dub": "字幕/配音/翻译现有视频",
    "podcast-repurpose": "播客精华→视频",
    "screen-demo": "软件屏幕录制演示",
    "talking-head": "实拍发言人视频",
    "framework-smoke": "测试桩管线",
}


def identify_pipeline(user_request: str) -> list[str]:
    """根据用户请求识别候选 pipeline。

    对应 OpenMontage Rule Zero：匹配 pipeline_defs/ 中的 pipeline。
    """
    request_lower = user_request.lower()

    # 关键词映射
    keywords = {
        "animated-explainer": ["explainer", "explainer video", "解释", "讲解", "解释视频", "animated explainer"],
        "animation": ["animation", "动画", "motion graphics", "动态图形", "kinetic typography"],
        "avatar-spokesperson": ["avatar", "数字人", "发言人", "spokesperson", "presenter"],
        "character-animation": ["character animation", "角色动画", "svg rig", "character", "人物动画"],
        "cinematic": ["cinematic", "电影感", "trailer", "预告片", "brand film", "品牌片"],
        "clip-factory": ["clip factory", "clip factory", "批量切片", "短视频批量", "repurpose"],
        "documentary-montage": ["documentary", "纪录片", "montage", "蒙太奇", "real footage", "真实素材", "archive"],
        "hybrid": ["hybrid", "混合", "source plus", "素材加生成"],
        "localization-dub": ["localization", "localisation", "dub", "配音", "翻译", "subtitle", "字幕"],
        "podcast-repurpose": ["podcast", "播客", "audio to video", "音频转视频"],
        "screen-demo": ["screen demo", "屏幕演示", "软件演示", "screen recording", "屏幕录制"],
        "talking-head": ["talking head", "实拍", "发言人", "interview", "采访", "vlog"],
    }

    matches = []
    for pipeline, kws in keywords.items():
        if any(kw in request_lower for kw in kws):
            matches.append(pipeline)

    return matches if matches else ["animated-explainer"]


def select_pipeline(
    user_request: str,
    available_tools: dict[str, Any] | None = None,
    budget_usd: float = 2.0,
) -> dict[str, Any]:
    """选择 pipeline 并返回完整规划。

    对应 AGENT_GUIDE.md: "Identify the pipeline" + "Read the pipeline manifest" + "Run preflight"
    """
    candidates = identify_pipeline(user_request)

    # 如果用户明确指定了 pipeline，优先使用
    selected = candidates[0] if len(candidates) == 1 else "animated-explainer"

    # 加载 manifest
    manifest_path = Path(__file__).parent.parent.parent.parent / "tools" / "pipeline_defs" / f"{selected}.yaml"
    if not manifest_path.exists():
        # 尝试相对路径
        manifest_path = Path("tools/pipeline_defs") / f"{selected}.yaml"
    if not manifest_path.exists():
        # 使用默认 manifest
        manifest = make_default_pipeline_manifest(selected)
    else:
        manifest = load_pipeline_manifest(manifest_path)

    # Preflight
    preflight_result = pipeline_preflight(manifest_path, available_tools)

    # 初始化成本预算
    budget = make_default_cost_budget(budget_usd)

    return {
        "selected_pipeline": selected,
        "candidates": candidates,
        "manifest": manifest,
        "preflight": preflight_result,
        "budget": budget,
        "checkpoint_policy": manifest.default_checkpoint_policy,
        "stages": [s.name for s in manifest.stages],
    }


def plan_stage(
    pipeline: str,
    stage: str,
    available_artifacts: dict[str, Any],
    available_tools: dict[str, Any],
    budget: CostBudget,
) -> dict[str, Any]:
    """规划单个阶段的执行。

    对应 AGENT_GUIDE.md: "For EACH stage, read the stage director skill BEFORE doing any work"
    """
    # 查找 stage 定义
    manifest = load_pipeline_manifest(f"tools/pipeline_defs/{pipeline}.yaml")
    stage_def = next((s for s in manifest.stages if s.name == stage), None)

    if not stage_def:
        return {"error": f"Stage {stage} not found in pipeline {pipeline}"}

    plan = {
        "pipeline": pipeline,
        "stage": stage,
        "stage_def": stage_def.model_dump(),
        "available_artifacts": list(available_artifacts.keys()),
        "required_artifacts_in": stage_def.required_artifacts_in,
        "optional_artifacts_in": stage_def.optional_artifacts_in,
        "required_tools": stage_def.required_tools,
        "optional_tools": stage_def.optional_tools,
        "tools_available": stage_def.tools_available,
        "checkpoint_required": stage_def.checkpoint_required,
        "human_approval_default": stage_def.human_approval_default,
        "review_focus": stage_def.review_focus,
        "success_criteria": stage_def.success_criteria,
        "budget_remaining": budget.remaining(),
    }

    return plan


def plan_full_pipeline(
    pipeline_name: str,
    available_tools: dict[str, Any] | None = None,
    budget_usd: float = 2.0,
) -> dict[str, Any]:
    """规划完整 pipeline 执行。

    生成完整的 stage-by-stage 执行计划。
    """
    manifest_path = Path("tools/pipeline_defs") / f"{pipeline_name}.yaml"
    if manifest_path.exists():
        manifest = load_pipeline_manifest(manifest_path)
        preflight = pipeline_preflight(manifest_path, available_tools)
    else:
        # 使用默认 manifest（OpenMontage 标准 pipeline 结构）
        manifest = make_default_pipeline_manifest(pipeline_name)
        preflight = {"budget_default_usd": budget_usd, "validation_errors": []}

    make_default_cost_budget(budget_usd)

    stages_plan = [
        {
            "stage": stage_def.name,
            "skill": stage_def.skill,
            "required_artifacts_in": stage_def.required_artifacts_in,
            "produces": stage_def.produces,
            "checkpoint_required": stage_def.checkpoint_required,
            "human_approval_default": stage_def.human_approval_default,
            "review_focus": stage_def.review_focus,
            "success_criteria": stage_def.success_criteria,
            "required_tools": stage_def.required_tools,
        }
        for stage_def in manifest.stages
    ]

    return {
        "pipeline": pipeline_name,
        "manifest_version": manifest.version,
        "total_stages": len(manifest.stages),
        "stages": stages_plan,
        "budget_usd": budget_usd,
        "preflight": preflight,
        "checkpoint_policy": manifest.default_checkpoint_policy,
        "orchestration": {
            "mode": manifest.orchestration_mode,
            "skill": manifest.orchestration_skill,
            "max_revisions_per_stage": manifest.max_revisions_per_stage,
            "max_send_backs": manifest.max_send_backs,
            "max_wall_time_minutes": manifest.max_wall_time_minutes,
        },
    }


# ─── Reference Video Analysis ───────────────────────


def plan_reference_analysis(
    video_path: str | Path,
    analysis_tools: list[str] | None = None,
) -> dict[str, Any]:
    """规划参考视频分析。

    对应 AGENT_GUIDE.md: "Read video-reference-analyst.md" + "Run the reference analysis workflow"
    """
    if analysis_tools is None:
        analysis_tools = [
            "video_analyzer",
            "transcript_fetcher",
            "video_downloader",
            "scene_detect",
            "frame_sampler",
        ]

    return {
        "video_path": str(video_path),
        "analysis_tools": analysis_tools,
        "expected_output": {
            "content": "内容摘要",
            "pacing": "节奏分析",
            "structure": "结构分析",
            "style": "风格识别",
            "what_makes_it_work": "关键成功因素",
            "concepts": "2-3 个差异化概念",
        },
    }


# ─── Delivery Planning ──────────────────────────────


def plan_delivery(
    pipeline: str,
    render_report: dict[str, Any],
    platforms: list[str] | None = None,
) -> dict[str, Any]:
    """规划交付阶段。"""
    if platforms is None:
        platforms = ["youtube", "bilibili", "tiktok", "instagram"]

    return {
        "pipeline": pipeline,
        "render_report": render_report,
        "platforms": platforms,
        "steps": [
            {"step": "export_bundle", "tool": "export_bundle"},
            {"step": "publish_matrix", "tool": "publish.matrix", "platforms": platforms},
        ],
        "checklist": [
            "SEO metadata complete and keyword-rich",
            "Chapter markers present",
            "Export package structured correctly",
            "Thumbnail concept generated",
        ],
    }


# ─── Execute Pipeline (适配 hevi studio pipeline 执行器) ───────────────────


async def execute_pipeline(
    pipeline: str,
    input_data: dict[str, Any],
    available_tools: dict[str, Any] | None = None,
    budget_usd: float = 2.0,
    output_dir: str | None = None,
    *,
    auto_approve: bool = False,
    resume: bool = True,
) -> dict[str, Any]:
    """Compatibility entry point backed by the executable HEVI transaction.

    Older callers can keep the original positional signature; new callers may
    opt into explicit approval/resume controls.  There is no placeholder
    compose result and no implicit approval anymore.
    """
    from hevi.montage.omodul.agentic import agentic_montage_workflow

    return await agentic_montage_workflow(
        {
            "pipeline": pipeline,
            "budget_usd": budget_usd,
            "execute": True,
            "auto_approve": auto_approve,
            "resume": resume,
        },
        {**input_data, "available_tools": available_tools},
        output_dir or f"output/montage/{pipeline}",
    )


# ─── 导出 ───────────────────────────────────────────

__all__ = [
    "AVAILABLE_PIPELINES",
    "AgenticMontageConfig",
    "agentic_montage_workflow",
    "execute_pipeline",
    "VideoEvidenceConfig",
    "compute_video_agent_fingerprint",
    "video_agent_transaction",
    "video_evidence_index",
    "video_evidence_search",
    "video_script_from_transcript",
    "identify_pipeline",
    "plan_delivery",
    "plan_full_pipeline",
    "plan_reference_analysis",
    "plan_stage",
    "select_pipeline",
]
