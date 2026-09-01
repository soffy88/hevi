"""montage oskill：组合 ≥2 个 oprim 原子，不得引用 omodul。

OpenMontage stage director skills：pipeline orchestration + stage director logic
每个技能都是 oprim 原语的组合，对应 pipeline_defs/*.yaml 阶段
"""

from __future__ import annotations

import asyncio
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
from hevi.montage.oskill.video_agent import (
    build_video_agent_plan,
    infer_video_intent,
    rank_evidence_candidates,
    reflect_video_agent_plan,
)
from hevi.montage.schemas import (
    Artifact,
    ArtifactType,
    CheckpointState,
    CostBudget,
    PipelineManifest,
    StageDef,
    ToolCapability,
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

    if available_tools is None:
        # Use HEVI's live tool registry.  The upstream OpenMontage directory is
        # intentionally not a runtime dependency.
        from hevi.studio.tools import list_tools

        capability_map = {
            "watch": ToolCapability.VIDEO_ANALYZE,
            "research": ToolCapability.RESEARCH,
            "script": ToolCapability.SCRIPT,
            "tts": ToolCapability.TTS,
            "material": ToolCapability.STOCK_VIDEO,
            "score": ToolCapability.ENHANCEMENT,
            "nle": ToolCapability.EDIT_PLAN,
            "delivery": ToolCapability.DELIVERY,
            "publish": ToolCapability.PUBLISH,
            "runtime": ToolCapability.VIDEO_COMPOSE,
            "director": ToolCapability.EDIT_PLAN,
        }
        tools_registry = {
            spec.tool_id: ToolContract(
                name=spec.tool_id,
                capability=capability_map.get(spec.kind, ToolCapability.ENHANCEMENT),
                provider="hevi",
                summary=spec.summary,
            )
            for spec in list_tools()
        }
    else:
        tools_registry = available_tools
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
    key = f"slate:{data.get('slate_id', 'anon')}"
    payload = {"line_id": data.get("line_id"), "topic": topic[:200]}
    store = data.get("memory_store")
    if store is None:
        from hevi.memory.store import MemoryStore

        store = MemoryStore(Path(str(data.get("memory_db") or "data/memory/montage.db")))
    memory_id = store.remember("short_term", key, payload)
    return {
        "topic": topic,
        "intake": {"key": key, "memory_id": memory_id, "payload": payload},
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
    research_fn = data.get("research_fn")
    if callable(research_fn):
        result = research_fn(topic, angles or ["fact", "worldview"])
        if hasattr(result, "__await__"):
            return {
                "research": {"topic": topic, "angles": angles, "research_fn": "async"},
                "research_status": "blocked",
                "research_reason": "sync stage_research received an async provider; use studio.stages.stage_research",
            }
        return {"research": result if isinstance(result, dict) else {"result": result}, "research_status": "completed"}
    from hevi.research.brief import plan_research_questions

    questions = plan_research_questions(str(topic), list(angles or ["fact", "worldview"])) if topic else []
    result = {
        "topic": topic,
        "angles": angles,
        "research_brief": {
            "data_points": [],
            "angles_discovered": questions,
            "sources_cited": [],
            "status": "questions_only",
        },
    }
    return {
        "research": result,
        "research_status": "planned",
        "research_reason": "未注入 web/LLM researcher；已生成可执行问题，不冒充事实来源",
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
    tool_name = str(data.get("score_tool") or "video/shot")
    candidates = data.get("provider_candidates") or []
    decision_log = data.get("decision_log") or ""
    winner: Any = None
    explain = ""
    if candidates and all(isinstance(item, dict) for item in candidates):
        from hevi.providers.scoring import choose_provider

        selected = choose_provider(tool_name, candidates, reason=f"line:{data.get('line_id', '')}")
        if selected is not None:
            winner = selected.provider
            explain = selected.explain()
    elif candidates:
        winner = candidates[0]

    return {
        "provider_decision": {
            "winner": winner,
            "candidates": candidates,
            "log": decision_log,
            "explain": explain,
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
        from hevi.studio.assets import bind_asset

        ref = bind_asset(
            "subject",
            line_id=str(data.get("line_id") or "studio"),
            label=str(subject),
            payload={"subject_id": subject},
        )
        bound_assets.append({**ref.to_dict(), "status": "bound"})

    from hevi.video.material_corpus import MaterialInfo, rank_by_keywords

    items = [
        MaterialInfo(
            source=str(item.get("source") or "local"),
            id=str(item.get("id") or ""),
            url=str(item.get("url") or ""),
            title=str(item.get("title") or ""),
            keywords=tuple(item.get("keywords") or ()),
            width=int(item.get("width") or 0),
            height=int(item.get("height") or 0),
            duration_s=float(item.get("duration_s") or 0.0),
            cached_path=str(item.get("cached_path") or ""),
        )
        for item in data.get("materials") or []
        if isinstance(item, dict) and item.get("id")
    ]
    ranked_materials = [
        item.to_dict()
        for item in rank_by_keywords(
            items,
            str(data.get("topic") or ""),
            target_aspect=str(data.get("aspect_ratio") or ""),
        )
    ]

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
    materials = data.get("ranked_materials") or data.get("materials") or []
    cuts: list[dict[str, Any]] = []
    cursor = 0.0
    for index, item in enumerate(script_lines):
        has_duration = isinstance(item, dict) and item.get("duration_s") is not None
        if isinstance(item, dict):
            text = str(item.get("text") or item.get("line") or "").strip()
            duration = float(item.get("duration_s") or 8.0)
        else:
            text = str(item).strip()
            duration = 8.0
        if not text and not has_duration:
            continue
        visual = materials[index].get("url") if index < len(materials) and isinstance(materials[index], dict) else None
        cuts.append({"index": index, "start_s": cursor, "duration_s": max(0.4, duration), "text": text, "visual": visual, "action": "keep"})
        cursor += max(0.4, duration)
    edit_plan = {
        "edit_plan": {
            "kind": "nle_edit_plan",
            "cuts": cuts,
            "total_s": round(cursor, 3),
            "script_lines": script_lines,
        },
        "preview_gate": {
            "total_s": round(cursor, 3)
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
    script = data.get("script") or data.get("script_lines") or []
    if not script:
        return {"mix": None, "mix_status": "skipped"}
    return {
        "mix": {
            "cue_points": script,
            "deductions": [],
            "final_mix": None,
        },
        "mix_status": "planned",
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
    if isinstance(plan.get("edit_plan"), dict):
        plan = plan["edit_plan"]
    from hevi.studio.timeline import timeline_from_edit_plan

    timeline = timeline_from_edit_plan(plan, title=str(title))
    return {
        "timeline": timeline.to_dict(),
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

    # 同步兼容入口也不再把“已发工单”冒充为完成。没有 execute 时只是
    # 可审查计划；显式 execute 且当前不在事件循环时才真正消费工单。
    fulfillment: dict[str, Any] = {"status": "planned", "target": handoff}
    if data.get("execute"):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            from hevi.studio.fulfill import fulfill_order

            destination = data.get("output_dir") or f"output/studio/{slate_id or 'order'}"
            fulfillment = asyncio.run(fulfill_order(order, execute=True, output_dir=destination))
        else:
            fulfillment = {
                "status": "blocked",
                "target": handoff,
                "reason": "同步 stage_dispatch 不能在运行中的事件循环执行；请使用 hevi.studio.stages.stage_dispatch",
            }
    return {
        "production_order": order,
        "fulfill": fulfillment,
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
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            from hevi.publishers import publish_to_platform

            result = asyncio.run(
                publish_to_platform(
                    str(platform),
                    Path(str(media)),
                    title=str(data.get("title") or data.get("topic") or ""),
                    description=str(data.get("description") or ""),
                    tags=list(data.get("tags") or []),
                )
            )
            results.append(result.to_dict())
        else:
            results.append(
                {
                    "platform": platform,
                    "status": "blocked",
                    "media_path": str(media),
                    "reason": "同步 stage_publish 不能在运行中的事件循环执行；请使用 hevi.studio.stages.stage_publish",
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
    "build_video_agent_plan",
    "infer_video_intent",
    "rank_evidence_candidates",
    "reflect_video_agent_plan",
]
