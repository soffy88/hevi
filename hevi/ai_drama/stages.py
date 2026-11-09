"""Studio stages for the ai_drama line (async, one stage per canvas node)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .pipeline import Pipeline


def _pipeline(data: dict[str, Any]) -> tuple[Pipeline, dict[str, Any]]:
    out = Path(str(data.get("out_dir") or "output/ai_drama"))
    p = Pipeline(
        out,
        episode_id=str(data.get("episode_id") or data.get("slate_id") or "ai_drama"),
        budget_cny=data.get("budget_cny"),
        prefer_provider=data.get("video_provider") or data.get("provider"),
        seed=int(data.get("seed") or 42),
        lipsync=data.get("lipsync"),
        render_images=bool(data.get("render_images", True)),
    )
    state = data.get("ai_drama_state") or {}
    state["input"] = data.get("episode") or {"theme": data.get("topic") or "一个日常里的异常",
                                            "style": data.get("style") or "live_action"}
    p.state = state
    p.report = data.get("ai_drama_report") or {"episode_id": p.episode_id, "nodes": {}, "line": "ai_drama"}
    return p, state


async def _run(stage: str, data: dict[str, Any], _ctx: Any) -> dict[str, Any]:
    p, _state = _pipeline(data)
    fn = getattr(p, f"stage_{stage}")
    check = getattr(p, f"_check_{stage}")
    payload = p.run_node(stage, fn, check)
    return {
        **{k: v for k, v in data.items() if k not in ("ai_drama_state", "ai_drama_report")},
        **payload,
        "ai_drama_state": p.state,
        "ai_drama_report": p.report,
        "ai_drama_node": stage,
    }


async def stage_script(data: dict[str, Any], ctx: Any) -> dict[str, Any]:
    return await _run("script", data, ctx)


async def stage_storyboard(data: dict[str, Any], ctx: Any) -> dict[str, Any]:
    return await _run("storyboard", data, ctx)


async def stage_assets(data: dict[str, Any], ctx: Any) -> dict[str, Any]:
    return await _run("assets", data, ctx)


async def stage_voice(data: dict[str, Any], ctx: Any) -> dict[str, Any]:
    return await _run("voice", data, ctx)


async def stage_segments(data: dict[str, Any], ctx: Any) -> dict[str, Any]:
    return await _run("segments", data, ctx)


async def stage_edit(data: dict[str, Any], ctx: Any) -> dict[str, Any]:
    return await _run("edit", data, ctx)


async def stage_delivery(data: dict[str, Any], ctx: Any) -> dict[str, Any]:
    return await _run("delivery", data, ctx)


async def produce(data: dict[str, Any], _ctx: Any) -> dict[str, Any]:
    p, _ = _pipeline(data)
    report = p.run(p.state["input"])
    return {**data, "ai_drama_report": report, "delivery": report.get("delivery")}
