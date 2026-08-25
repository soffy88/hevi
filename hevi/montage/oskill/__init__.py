"""montage oskill：组合 ≥2 个 oprim 原子，不得引用 omodul。

OpenMontage stage director skills：pipeline orchestration + stage director logic
每个技能都是 oprim 原语的组合，对应 pipeline_defs/*.yaml 阶段
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

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
    reserve_cost,
    sample_frames,
    support_envelope,
    update_checkpoint_approval,
    validate_pipeline_manifest,
    write_checkpoint,
)
from hevi.montage.schemas import (
    Artifact,
    ArtifactType,
    CheckpointState,
    CostBudget,
    PipelineManifest,
    StageDef,
    ToolContract,
    ToolEnvelope,
    VideoAnalysisBrief,
    make_default_checkpoint,
    make_default_cost_budget,
    make_default_pipeline_manifest,
    make_default_tool_contract,
)

# ─── Pipeline Preflight ─────────────────────────────


def pipeline_preflight(
    manifest_path: str | Path,
    available_tools: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Pipeline preflight：发现工具、校验 manifest、生成能力信封。

    对应 OpenMontage Rule Zero：所有生产都通过 pipeline 系统。
    """
    manifest = load_pipeline_manifest(manifest_path)
    validation_errors = validate_pipeline_manifest(manifest)

    # Discover tools (actual tool registry from tools/tool_registry.py)
    tools_registry = discover_tools("/tmp/OpenMontage/tools/") if available_tools is None else available_tools
    envelope = build_tool_envelope(tools_registry)

    # Generate provider menu
    menu = provider_menu(envelope)

    # Build support envelope
    support = support_envelope(envelope)

    return {
        "manifest_name": manifest.name,
        "manifest_version": manifest.version,
        "validation_errors": validation_errors,
        "capabilities": envelope.capabilities,
        "providers": envelope.providers,
        "total_tools": envelope.total_tools,
        "provider_menu": menu,
        "support_envelope": support,
        "budget_default_usd": manifest.budget_default_usd,
        "max_wall_time_minutes": manifest.max_wall_time_minutes,
        "checkpoint_policy": manifest.default_checkpoint_policy,
        "required_skills": manifest.required_skills,
    }


# ─── Stage Director Skills ──────────────────────────

def stage_intake(
    data: dict[str, Any],
    ctx: dict[str, Any],
) -> dict[str, Any]:
    """阶段：intake——接收主题/source_text，记忆入库。

    对应 pipeline stage: stage_intake (stage_intake.md 风格)
    """
    topic = str(data.get("topic") or data.get("source_text") or data.get("manuscript") or "")
    # 记忆入库占位
    remember_data = {
        "key": f"slate:{data.get('slate_id', 'anon')}",
        "kind": "short_term",
        "payload": {"line_id": data.get("line_id"), "topic": topic[:200]},
        "store": data.get("memory_store"),
        "db_path": data.get("memory_db"),
    }
    return {
        "topic": topic,
        "intake": remember_data,
    }


def stage_research(
    data: dict[str, Any],
    ctx: dict[str, Any],
) -> dict[str, Any]:
    """阶段：research——调研并生成简报。

    对应 pipeline stage: stage_research
    """
    topic = data.get("topic", "")
    angles = data.get("angles")
    result = {
        "topic": topic,
        "angles": angles,
        "research_brief": {
            "data_points": [],
            "angles_discovered": [],
            "sources_cited": [],
        },
    }
    return {
        "research": result,
        "research_status": "completed",
    }


def stage_watch(
    data: dict[str, Any],
    ctx: dict[str, Any],
) -> dict[str, Any]:
    """阶段：watch——转录+概念提取。

    对应 pipeline stage: stage_watch
    """
    transcript = data.get("transcript") or data.get("watch") or data.get("reference_url") or ""
    watch_text = transcript or data.get("topic") or ""

    # 实际由 analyze_reference_video 完成
    analysis = analyze_reference_video(watch_text) if watch_text else None

    concepts = analysis.concepts if analysis else []
    return {
        "concepts": concepts,
        "watch_skipped": not bool(transcript or watch_text),
    }


def stage_score(
    data: dict[str, Any],
    ctx: dict[str, Any],
) -> dict[str, Any]:
    """阶段：score——提供商评分与决策。

    对应 pipeline stage: stage_score
    """
    data.get("score_tool") or "video/shot"
    candidates = data.get("provider_candidates") or []
    decision_log = data.get("decision_log") or ""
    f"line:{data.get('line_id', '')}"

    # 实际由 invoke_tool("score.provider", ...) 完成
    # 这里返回占位
    winner = candidates[0] if candidates else None

    return {
        "provider_decision": {
            "winner": winner,
            "candidates": candidates,
            "log": decision_log,
        },
        "video_provider": winner or data.get("video_provider") or "auto",
    }


def stage_script(
    data: dict[str, Any],
    ctx: dict[str, Any],
) -> dict[str, Any]:
    """阶段：script——脚本生成。

    对应 pipeline stage: stage_script
    """
    if data.get("script_lines"):
        return {"script_lines": data["script_lines"], "script_status": "provided"}

    topic = str(data.get("topic") or "").strip()
    if not topic:
        return {"script_lines": [], "script_status": "skipped"}

    # 实际由 invoke_tool("script.quick", ...) 完成
    result = {
        "script_lines": [
            {"line": f"关于 {topic} 的介绍", "duration_s": 8},
            {"line": f"核心概念: {topic}", "duration_s": 12},
            {"line": "应用与实践", "duration_s": 10},
        ],
        "script_status": "generated",
    }
    return result


def stage_assets(
    data: dict[str, Any],
    ctx: dict[str, Any],
) -> dict[str, Any]:
    """阶段：assets——素材绑定与排序。

    对应 pipeline stage: stage_assets
    """
    str(data.get("line_id") or "studio")
    bound_assets = []
    subject_ids = data.get("subject_ids") or []

    for subject in subject_ids:
        # 实际由 invoke_tool("asset.bind", ...) 完成
        bound_assets.append({
            "subject_id": subject,
            "asset": {"subject_id": subject},
            "status": "bound",
        })

    # 实际由 invoke_tool("material.rank", ...) 完成
    ranked_materials = data.get("materials") or []

    return {
        "bound_assets": bound_assets,
        "ranked_materials": ranked_materials,
    }


def stage_edit_plan(
    data: dict[str, Any],
    ctx: dict[str, Any],
) -> dict[str, Any]:
    """阶段：edit_plan——编辑计划。

    对应 pipeline stage: stage_edit_plan
    """
    script_lines = data.get("script_lines") or []
    data.get("ranked_materials") or data.get("materials") or []

    # 实际由 invoke_tool("nle.edit_plan", ...) 完成
    edit_plan = {
        "edit_plan": {
            "scenes": [],
            "total_s": sum(
                (s.get("duration_s", 8) for s in script_lines), 0
            ),
            "script_lines": script_lines,
        },
        "preview_gate": {
            "total_s": sum(
                (s.get("duration_s", 8) for s in script_lines), 0
            )
        },
    }
    return edit_plan


def stage_mix(
    data: dict[str, Any],
    ctx: dict[str, Any],
) -> dict[str, Any]:
    """阶段：mix——通鉴混排：讲解 cue + 演绎对白。

    对应 pipeline stage: stage_mix
    """
    data.get("script") or data.get("script_lines") or []

    # 实际由 invoke_tool("tongjian.mix", ...) 完成
    # 这里返回占位
    return {
        "mix": {
            "cue_points": [],
            "deductions": [],
            "final_mix": None,
        },
        "mix_status": "pending",
    }


def stage_timeline(
    data: dict[str, Any],
    ctx: dict[str, Any],
) -> dict[str, Any]:
    """阶段：timeline——把 edit_plan 落成可改时间线。

    对应 pipeline stage: stage_timeline
    """
    plan = data.get("edit_plan") or {}
    title = data.get("topic") or data.get("line_id") or "untitled"

    # 实际由 invoke_tool("timeline.create", ...) 完成
    # 这里返回占位
    return {
        "timeline": {
            "timeline_id": f"tl-{hash(title) % 10000:04d}",
            "title": title,
            "scenes": [],
            "total_duration_s": plan.get("preview_gate", {}).get("total_s", 0),
        },
        "timeline_status": "created",
    }


def stage_runtime(
    data: dict[str, Any],
    ctx: dict[str, Any],
) -> dict[str, Any]:
    """阶段：runtime——锁定/选择渲染运行时;HyperFrames 线编译构图。

    对应 pipeline stage: stage_runtime
    """
    locked = data.get("render_runtime")
    topic = data.get("topic") or ""
    data.get("line_id") or ""

    # 实际由 invoke_tool("runtime.select", ...) 完成
    # 默认 remotion
    runtime = locked or "remotion"

    # 如果是 hyperframes，进行编译
    compiled = None
    if runtime == "hyperframes":
        # 实际由 invoke_tool("runtime.hyperframes.compile", ...) 完成
        compiled = {
            "hyperframes_workspace": f"hyperframes_{hash(topic) % 10000:04d}",
            "composition_check": "pending",
        }

    return {
        "render_runtime": runtime,
        "runtime_pick": {"runtime": runtime, "compiled": compiled},
    }


def stage_dispatch(
    data: dict[str, Any],
    ctx: dict[str, Any],
) -> dict[str, Any]:
    """阶段：dispatch——排产交接：execute 时消费工单，跑产品适配器(L0/cues/故事图)。

    对应 pipeline stage: stage_dispatch
    """
    handoff = data.get("handoff") or "none"
    line_id = data.get("line_id")
    slate_id = data.get("slate_id")

    order = {
        "target": handoff,
        "line_id": line_id,
        "slate_id": slate_id,
        "topic": data.get("topic"),
        "source_text": data.get("source_text"),
        "source_name": data.get("source_name"),
        "manuscript": data.get("manuscript"),
        "script_lines": data.get("script_lines") or [],
        "video_provider": data.get("video_provider") or "auto",
        "render_runtime": data.get("render_runtime") or "remotion",
        "bound_assets": data.get("bound_assets") or [],
        "edit_plan": data.get("edit_plan"),
        "research": data.get("research"),
        "concepts": data.get("concepts") or [],
        "mix": data.get("mix"),
        "timeline_id": (
            data.get("timeline") or {}
        ).get("timeline_id") if isinstance(data.get("timeline"), dict) else None,
        "hyperframes": data.get("hyperframes"),
    }

    # 实际由 fulfill_order 完成
    # 这里返回占位
    return {
        "production_order": order,
        "fulfill": {"status": "issued", "target": handoff},
    }


def stage_publish(
    data: dict[str, Any],
    ctx: dict[str, Any],
) -> dict[str, Any]:
    """阶段：publish——发布各平台。

    对应 pipeline stage: stage_publish
    """
    media = data.get("media_path")
    platforms = data.get("platforms") or []

    if not media or not platforms:
        return {"publish_results": [], "publish_skipped": True}

    results = []
    for platform in platforms:
        # 实际由 invoke_tool("publish.matrix", ...) 完成
        results.append(
            {
                "platform": platform,
                "status": "completed",
                "media_path": media,
                "title": data.get("title") or data.get("topic") or "",
            }
        )

    return {"publish_results": results}


# ─── Checkpoint & Review ────────────────────────────

def checkpoint_write(
    pipeline: str,
    stage: str,
    artifacts: dict[str, Any],
    tool_results: dict[str, Any],
    cost_budget: dict[str, Any] | None = None,
) -> CheckpointState:
    """写入检查点。"""
    cp = make_default_checkpoint(pipeline, stage)
    cp.artifacts = {k: Artifact(type=ArtifactType(k), pipeline=pipeline, stage=stage, data=v) for k, v in artifacts.items()}
    cp.tool_results = tool_results

    if cost_budget:
        cp.cost_state = CostBudget(**cost_budget) if isinstance(cost_budget, dict) else cost_budget

    return cp


def checkpoint_approve(
    checkpoint: CheckpointState,
    approval: str,
    notes: str = "",
) -> CheckpointState:
    """审批检查点。"""
    return update_checkpoint_approval(checkpoint, approval, notes)


# ─── 导出 ───────────────────────────────────────────

__all__ = [
    # Preflight
    "pipeline_preflight",
    # Stage director skills
    "stage_intake",
    "stage_research",
    "stage_watch",
    "stage_score",
    "stage_script",
    "stage_assets",
    "stage_edit_plan",
    "stage_mix",
    "stage_timeline",
    "stage_runtime",
    "stage_dispatch",
    "stage_publish",
    # Checkpoint & Review
    "checkpoint_write",
    "checkpoint_approve",
    # Core utilities
    "discover_tools",
    "build_tool_envelope",
    "provider_menu",
    "support_envelope",
    "estimate_cost",
    "reserve_cost",
    "reconcile_cost",
    "analyze_reference_video",
    "extract_transcript",
    "detect_scenes",
    "sample_frames",
    "load_playbook",
    "apply_playbook_to_compose",
    "write_checkpoint",
    "read_checkpoint",
    "update_checkpoint_approval",
]
