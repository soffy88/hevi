"""stickman capabilities —— 统一能力契约注册。

按照 CAPABILITY_CONTRACT.md 与 STICKMAN_TASK.md 规范，将火柴人能力全量注册进
Hevi 统一能力注册表（hevi.capabilities）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hevi.capabilities import Capability, CapabilityError, CapabilityResult, register
from hevi.stickman.topic_scout import scout_topics
from hevi.stickman.structure_clone import clone_structure
from hevi.stickman.proposal import (
    create_proposal_from_script,
    DirectorProposal,
    StoryboardScene,
    ProposalNotApprovedError,
)
from hevi.stickman.render_local import render_local_video
from hevi.stickman.flow_pack import export_flow_pack
from hevi.stickman.flow_import import import_and_stitch_flow_clips
from hevi.stickman.credits_ledger import CreditsLedger


def _render_topic_scout(
    params: dict[str, Any],
    out_dir: Path,
    *,
    duration: float,
    aspect: str,
    seed: int,
) -> CapabilityResult:
    source = params.get("source", "")
    min_views = int(params.get("min_views", 0))
    top_n = params.get("top_n")

    results = scout_topics(source, min_views=min_views, top_n=top_n)
    out_dir.mkdir(parents=True, exist_ok=True)
    report_file = out_dir / "scouted_topics.json"
    report_file.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

    return CapabilityResult(
        duration_s=duration,
        qa={
            "topics_count": len(results),
            "top_topic": results[0]["title"] if results else "",
            "top_score": results[0]["score"] if results else 0.0,
        },
    )


def _render_structure_clone(
    params: dict[str, Any],
    out_dir: Path,
    *,
    duration: float,
    aspect: str,
    seed: int,
) -> CapabilityResult:
    reference_script = params.get("reference_script", [])
    new_topic = str(params.get("new_topic", "为什么冰块放水里浮起来，放油里却沉下去？"))
    target_dur = float(params.get("target_duration", duration or 60.0))

    script_result = clone_structure(
        reference_script=reference_script,
        new_topic=new_topic,
        target_duration=target_dur,
        enforce_anti_copy=params.get("enforce_anti_copy", True),
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    out_json = out_dir / "structure_script.json"
    out_json.write_text(json.dumps(script_result, indent=2, ensure_ascii=False), encoding="utf-8")

    return CapabilityResult(
        duration_s=target_dur,
        qa={
            "topic": new_topic,
            "stages_count": len(script_result["stages"]),
            "facts_verified": len(script_result["fact_check_list"]),
        },
    )


def _render_proposal(
    params: dict[str, Any],
    out_dir: Path,
    *,
    duration: float,
    aspect: str,
    seed: int,
) -> CapabilityResult:
    script_data = params.get("script_data", {})
    art_style = str(params.get("art_style", "classic_minimalist"))
    auto_approve = bool(params.get("auto_approve", False))

    prop = create_proposal_from_script(
        script_data=script_data,
        aspect_ratio=aspect or "16:9",
        art_style=art_style,
    )
    if auto_approve:
        prop.approve()

    out_dir.mkdir(parents=True, exist_ok=True)
    prop_json = out_dir / "proposal.json"
    prop_json.write_text(json.dumps(prop.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

    return CapabilityResult(
        duration_s=prop.total_duration,
        qa={
            "proposal_id": prop.proposal_id,
            "status": prop.status,
            "scenes": len(prop.storyboard),
            "aspect_ratio": prop.aspect_ratio,
            "art_style": prop.art_style,
        },
    )


def _render_local_cap(
    params: dict[str, Any],
    out_dir: Path,
    *,
    duration: float,
    aspect: str,
    seed: int,
) -> CapabilityResult:
    prop_dict = params.get("proposal")
    if not isinstance(prop_dict, dict):
        raise CapabilityError("stickman.render_local requires 'proposal' dict in params")

    scenes = [StoryboardScene(**s) for s in prop_dict.get("storyboard", [])]
    proposal = DirectorProposal(
        proposal_id=prop_dict.get("proposal_id", "prop_cap"),
        title=prop_dict.get("title", "未命名"),
        topic=prop_dict.get("topic", "未命名"),
        hook=prop_dict.get("hook", ""),
        color_palette=prop_dict.get("color_palette", {}),
        storyboard=scenes,
        voiceover=prop_dict.get("voiceover", {}),
        bgm_style=prop_dict.get("bgm_style", ""),
        aspect_ratio=aspect or prop_dict.get("aspect_ratio", "16:9"),
        art_style=prop_dict.get("art_style", "classic_minimalist"),
        status=prop_dict.get("status", "draft"),
    )

    if proposal.status != "approved":
        raise CapabilityError("提案尚未批准(status != 'approved')，未批准不得出片")

    out_dir.mkdir(parents=True, exist_ok=True)
    out_mp4 = out_dir / "stickman_rendered.mp4"
    res = render_local_video(proposal, out_mp4)

    return CapabilityResult(
        mp4=res["out_path"],
        duration_s=res["duration_s"],
        qa=res["qa"],
    )


def _render_flow_pack_cap(
    params: dict[str, Any],
    out_dir: Path,
    *,
    duration: float,
    aspect: str,
    seed: int,
) -> CapabilityResult:
    prop_dict = params.get("proposal")
    if not isinstance(prop_dict, dict):
        raise CapabilityError("stickman.flow_pack requires 'proposal' dict in params")

    scenes = [StoryboardScene(**s) for s in prop_dict.get("storyboard", [])]
    proposal = DirectorProposal(
        proposal_id=prop_dict.get("proposal_id", "prop_cap"),
        title=prop_dict.get("title", "未命名"),
        topic=prop_dict.get("topic", "未命名"),
        hook=prop_dict.get("hook", ""),
        color_palette=prop_dict.get("color_palette", {}),
        storyboard=scenes,
        voiceover=prop_dict.get("voiceover", {}),
        bgm_style=prop_dict.get("bgm_style", ""),
        aspect_ratio=aspect or prop_dict.get("aspect_ratio", "16:9"),
        art_style=prop_dict.get("art_style", "classic_minimalist"),
        status=prop_dict.get("status", "draft"),
    )

    if proposal.status != "approved":
        raise CapabilityError("提案尚未批准(status != 'approved')，未批准不得出提示词包")

    ledger_file = out_dir / "credits_ledger.json"
    ledger = CreditsLedger(ledger_file)
    res = export_flow_pack(proposal, out_dir, ledger=ledger)

    return CapabilityResult(
        duration_s=proposal.total_duration,
        qa={
            "json_path": res["json_path"],
            "txt_path": res["txt_path"],
            "total_clips": res["total_clips"],
            "credits_spent": res["total_estimated_credits"],
        },
    )


def _render_flow_import_cap(
    params: dict[str, Any],
    out_dir: Path,
    *,
    duration: float,
    aspect: str,
    seed: int,
) -> CapabilityResult:
    clip_paths = params.get("clip_paths", [])
    prop_dict = params.get("proposal")
    if not clip_paths or not isinstance(prop_dict, dict):
        raise CapabilityError("stickman.flow_import requires 'clip_paths' and 'proposal'")

    scenes = [StoryboardScene(**s) for s in prop_dict.get("storyboard", [])]
    proposal = DirectorProposal(
        proposal_id=prop_dict.get("proposal_id", "prop_cap"),
        title=prop_dict.get("title", "未命名"),
        topic=prop_dict.get("topic", "未命名"),
        hook=prop_dict.get("hook", ""),
        color_palette=prop_dict.get("color_palette", {}),
        storyboard=scenes,
        voiceover=prop_dict.get("voiceover", {}),
        bgm_style=prop_dict.get("bgm_style", ""),
        aspect_ratio=aspect or prop_dict.get("aspect_ratio", "16:9"),
        art_style=prop_dict.get("art_style", "classic_minimalist"),
        status=prop_dict.get("status", "approved"),
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    out_mp4 = out_dir / "flow_stitched.mp4"
    res = import_and_stitch_flow_clips(clip_paths, proposal, out_mp4)

    return CapabilityResult(
        mp4=res["out_path"],
        duration_s=res["duration_s"],
        qa=res["qa"],
    )


_STICKMAN_ASPECTS = ["16:9", "9:16"]


def register_stickman_capabilities_once() -> None:
    register(Capability(
        name="stickman.topic_scout",
        kind="shot",
        aspects=_STICKMAN_ASPECTS,
        params_schema={
            "type": "object",
            "properties": {
                "source": {"type": ["string", "array"]},
                "min_views": {"type": "integer"},
                "top_n": {"type": "integer"},
            },
            "required": ["source"],
        },
        cpu_cost_hint=0.1,
        render=_render_topic_scout,
        description="对标频道数据少发高爆打分排序器（离线纯算法）",
        line="stickman",
    ))

    register(Capability(
        name="stickman.structure_clone",
        kind="shot",
        aspects=_STICKMAN_ASPECTS,
        params_schema={
            "type": "object",
            "properties": {
                "reference_script": {"type": ["array", "object"]},
                "new_topic": {"type": "string"},
                "target_duration": {"type": "number"},
                "enforce_anti_copy": {"type": "boolean"},
            },
            "required": ["new_topic"],
        },
        cpu_cost_hint=0.2,
        render=_render_structure_clone,
        description="五段心跳骨架时间比例自适应克隆与反抄袭生成器",
        line="stickman",
    ))

    register(Capability(
        name="stickman.proposal",
        kind="shot",
        aspects=_STICKMAN_ASPECTS,
        params_schema={
            "type": "object",
            "properties": {
                "script_data": {"type": "object"},
                "art_style": {"type": "string"},
                "auto_approve": {"type": "boolean"},
            },
            "required": ["script_data"],
        },
        cpu_cost_hint=0.1,
        render=_render_proposal,
        description="火柴人导演提案与状态机（草稿/批准权限隔离）",
        line="stickman",
    ))

    register(Capability(
        name="stickman.render_local",
        kind="shot",
        aspects=_STICKMAN_ASPECTS,
        params_schema={
            "type": "object",
            "properties": {
                "proposal": {"type": "object"},
            },
            "required": ["proposal"],
        },
        cpu_cost_hint=1.5,
        render=_render_local_cap,
        description="CPU-only 程序化火柴人本地渲染（白底黑线/彩色故事两套+双语字幕+微缩放转场）",
        line="stickman",
    ))

    register(Capability(
        name="stickman.flow_pack",
        kind="shot",
        aspects=_STICKMAN_ASPECTS,
        params_schema={
            "type": "object",
            "properties": {
                "proposal": {"type": "object"},
            },
            "required": ["proposal"],
        },
        cpu_cost_hint=0.1,
        render=_render_flow_pack_cap,
        description="Flow Omni Flash 720P 任务包导出器（画风锁定+积分台账）",
        line="stickman",
    ))

    register(Capability(
        name="stickman.flow_import",
        kind="shot",
        aspects=_STICKMAN_ASPECTS,
        params_schema={
            "type": "object",
            "properties": {
                "clip_paths": {"type": "array"},
                "proposal": {"type": "object"},
            },
            "required": ["clip_paths", "proposal"],
        },
        cpu_cost_hint=0.8,
        render=_render_flow_import_cap,
        description="Flow 外部成品导入校验、双语字幕压制与微转场拼接器",
        line="stickman",
    ))
