"""产线阶段 —— obase Stage 契约 (data, ctx) -> dict,全部转调 studio.tools。"""

from __future__ import annotations

import json
from typing import Any

from hevi.studio.tools import invoke_tool


async def stage_intake(data: dict[str, Any], _ctx: Any) -> dict[str, Any]:
    topic = str(data.get("topic") or data.get("source_text") or data.get("manuscript") or "")
    remember = await invoke_tool(
        "memory.remember",
        {
            "key": f"slate:{data.get('slate_id', 'anon')}",
            "kind": "short_term",
            "payload": {"line_id": data.get("line_id"), "topic": topic[:200]},
            "store": data.get("memory_store"),
            "db_path": data.get("memory_db"),
        },
    )
    return {"topic": topic, "intake": remember.to_dict()}


async def stage_research(data: dict[str, Any], _ctx: Any) -> dict[str, Any]:
    result = await invoke_tool(
        "research.brief" if data.get("caller") else "research.plan",
        {
            "topic": data.get("topic"),
            "angles": data.get("angles"),
            "caller": data.get("caller"),
        },
    )
    return {"research": result.payload, "research_status": result.status}


async def stage_watch(data: dict[str, Any], _ctx: Any) -> dict[str, Any]:
    if not (data.get("transcript") or data.get("watch") or data.get("reference_url")):
        return {"concepts": [], "watch_skipped": True}
    result = await invoke_tool(
        "watch.concepts",
        {
            "watch": data.get("watch"),
            "transcript": data.get("transcript") or data.get("topic"),
            "duration_s": data.get("duration_s") or 0,
            "source": data.get("reference_url") or "studio",
            "llm": data.get("llm"),
        },
    )
    return {"concepts": result.payload.get("concepts") or []}


async def stage_score(data: dict[str, Any], _ctx: Any) -> dict[str, Any]:
    result = await invoke_tool(
        "score.provider",
        {
            "tool_name": data.get("score_tool") or "video/shot",
            "candidates": data.get("provider_candidates"),
            "decision_log": data.get("decision_log"),
            "reason": f"line:{data.get('line_id', '')}",
        },
    )
    winner = (result.payload.get("winner") or {}).get("provider")
    return {
        "provider_decision": result.payload,
        "video_provider": winner or data.get("video_provider") or "auto",
    }


async def stage_script(data: dict[str, Any], _ctx: Any) -> dict[str, Any]:
    if data.get("script_lines"):
        return {"script_lines": data["script_lines"]}
    if not str(data.get("topic") or "").strip():
        return {"script_lines": [], "script_status": "skipped"}
    result = await invoke_tool(
        "script.quick",
        {
            "topic": data.get("topic"),
            "target_duration_s": data.get("target_duration_s"),
            "max_lines": data.get("max_lines"),
        },
    )
    return {
        "script_lines": result.payload.get("script_lines") or [],
        "script_status": result.status,
    }


async def stage_assets(data: dict[str, Any], _ctx: Any) -> dict[str, Any]:
    line_id = str(data.get("line_id") or "studio")
    bound: list[dict[str, Any]] = []
    for subject in data.get("subject_ids") or []:
        res = await invoke_tool(
            "asset.bind",
            {
                "kind": "subject",
                "line_id": line_id,
                "label": str(subject),
                "asset": {"subject_id": subject},
            },
        )
        if res.payload.get("asset"):
            bound.append(res.payload["asset"])
    ranked = await invoke_tool(
        "material.rank",
        {
            "query": data.get("topic"),
            "items": data.get("materials") or [],
            "aspect": data.get("aspect_ratio") or "",
        },
    )
    return {
        "bound_assets": bound,
        "ranked_materials": ranked.payload.get("items") or [],
    }


async def stage_edit_plan(data: dict[str, Any], _ctx: Any) -> dict[str, Any]:
    result = await invoke_tool(
        "nle.edit_plan",
        {
            "script_lines": data.get("script_lines") or [],
            "materials": data.get("ranked_materials") or data.get("materials") or [],
        },
    )
    preview = await invoke_tool(
        "delivery.preview",
        {"estimate_s": (result.payload.get("edit_plan") or {}).get("total_s") or 0},
    )
    return {
        "edit_plan": result.payload.get("edit_plan"),
        "preview_gate": preview.payload,
    }


async def stage_mix(data: dict[str, Any], _ctx: Any) -> dict[str, Any]:
    """通鉴混排:讲解 cue + 演绎对白。"""
    result = await invoke_tool(
        "tongjian.mix",
        {"script": data.get("script") or data.get("script_lines") or []},
    )
    return {"mix": result.payload.get("mix"), "mix_status": result.status}


async def stage_timeline(data: dict[str, Any], _ctx: Any) -> dict[str, Any]:
    """把 edit_plan 落成可改时间线,后续改镜不再重跑产线。"""
    plan = data.get("edit_plan") or {}
    title = data.get("topic") or data.get("line_id") or "untitled"
    result = await invoke_tool("timeline.create", {"edit_plan": plan, "title": title})
    return {"timeline": result.payload.get("timeline"), "timeline_status": result.status}


async def stage_runtime(data: dict[str, Any], _ctx: Any) -> dict[str, Any]:
    """锁定/选择渲染运行时;HyperFrames 线编译构图。"""
    picked = await invoke_tool(
        "runtime.select",
        {
            "locked": data.get("render_runtime"),
            "intent": data.get("topic") or "",
            "line_id": data.get("line_id") or "",
        },
    )
    runtime = (picked.payload or {}).get("runtime") or data.get("render_runtime") or "remotion"
    out: dict[str, Any] = {"render_runtime": runtime, "runtime_pick": picked.payload}
    if runtime == "hyperframes":
        compiled = await invoke_tool(
            "runtime.hyperframes.compile",
            {
                "topic": data.get("topic"),
                "script_lines": data.get("script_lines") or [],
                "edit_plan": data.get("edit_plan") or {},
            },
        )
        out["hyperframes"] = compiled.payload
    return out


async def stage_dispatch(data: dict[str, Any], _ctx: Any) -> dict[str, Any]:
    """排产交接:execute 时消费工单,跑产品适配器(L0/cues/故事图)。"""
    handoff = str(data.get("handoff") or "none")
    raw_slots = data.get("input_slots") or {}
    safe_slots: dict[str, Any] = {}
    if isinstance(raw_slots, dict):
        for key, value in raw_slots.items():
            try:
                json.dumps(value, ensure_ascii=False)
            except (TypeError, ValueError):
                continue
            safe_slots[str(key)] = value
    order = {
        "target": handoff,
        "line_id": data.get("line_id"),
        "slate_id": data.get("slate_id"),
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
        "slots": safe_slots,
        "output_dir": data.get("output_dir"),
        "timeline_id": (data.get("timeline") or {}).get("timeline_id")
        if isinstance(data.get("timeline"), dict)
        else None,
        "hyperframes": data.get("hyperframes"),
    }
    fulfill: dict[str, Any] = {"status": "issued", "target": handoff}
    if data.get("execute"):
        from hevi.studio.fulfill import fulfill_order

        dest = data.get("output_dir") or f"output/studio/{data.get('slate_id') or 'order'}"
        fulfill = await fulfill_order(
            order,
            execute=True,
            output_dir=dest,
            render=True,
        )
    return {"production_order": order, "fulfill": fulfill}


async def stage_publish(data: dict[str, Any], _ctx: Any) -> dict[str, Any]:
    raw_fulfill = data.get("fulfill")
    fulfill: dict[str, Any] = raw_fulfill if isinstance(raw_fulfill, dict) else {}
    raw_media = data.get("media_path") or data.get("result_video_path") or fulfill.get("result_video_path")
    media = raw_media if isinstance(raw_media, str) else None
    platforms = data.get("platforms") or []
    if not media or not platforms:
        return {"publish_results": [], "publish_skipped": True}
    results = []
    for platform in platforms:
        res = await invoke_tool(
            "publish.matrix",
            {
                "platform": platform,
                "media_path": media,
                "title": data.get("title") or data.get("topic") or "",
                "tags": data.get("tags") or [],
            },
        )
        results.append(res.to_dict())
    return {"publish_results": results}
