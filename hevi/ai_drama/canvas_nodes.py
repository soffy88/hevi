"""Canvas glue for the ai_drama line.

The canvas executor passes each node's ``config`` plus its direct parents'
outputs.  These helpers thread one ``ai_drama_state`` document through the
stage nodes, so a failed node can be re-run on its own and the later nodes see
the same script/storyboard/assets/voice documents.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

STAGE_TOOLS: dict[str, str] = {
    "drama.stage_script": "script",
    "drama.stage_storyboard": "storyboard",
    "drama.stage_assets": "assets",
    "drama.stage_voice": "voice",
    "drama.stage_segments": "segments",
    "drama.stage_edit": "edit",
    "drama.stage_publish": "delivery",
}

SERIES_TOOLS = (
    "drama.style_cards",
    "drama.series_create",
    "drama.series_topics",
    "drama.series_beats",
    "drama.series_episode",
    "drama.series_review",
)

ALL_TOOLS = tuple(STAGE_TOOLS) + SERIES_TOOLS


def _merge(upstream: dict[str, Any] | None, payload: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for value in (upstream or {}).values():
        if isinstance(value, dict):
            merged.update(value)
    merged.update(payload or {})
    return merged


def _default_series(topic: str, series_dir: str | Path) -> dict[str, Any]:
    from .series import create_series, load_series

    path = Path(series_dir)
    try:
        return load_series(path)
    except FileNotFoundError:
        pass
    cast = [
        {
            "id": "c1", "name": "主角", "role": "lead",
            "hair": "短发", "hair_part": "三七分", "eye_color": "深棕",
            "signature_detail": "左眼下一颗小痣",
            "outfit": {"top": "浅色卫衣", "bottom": "深色长裤", "shoes": "白色帆布鞋"},
            "accessories": ["细手绳"], "personality": "嘴硬心软",
            "voice": {"description": "偏低、克制", "piper_voice": "zh_CN-huayan-medium.onnx",
                      "pitch_semitones": -1.0},
        },
        {
            "id": "c2", "name": "对方", "role": "partner",
            "hair": "马尾", "hair_part": "中分", "eye_color": "黑色",
            "signature_detail": "右耳一枚小耳钉",
            "outfit": {"top": "针织开衫", "bottom": "牛仔裤", "shoes": "棕色短靴"},
            "accessories": ["小耳钉"], "personality": "直率",
            "voice": {"description": "明亮、温和", "piper_voice": "zh_CN-huayan-medium.onnx",
                      "pitch_semitones": 1.5},
        },
    ]
    return create_series(title=topic or "未命名系列", genre="daily_anomaly", cast=cast,
                         out_dir=path, series_id="canvas_" + str(abs(hash(topic)) % 10**8))


def _seed_state(pipeline: Any, merged: dict[str, Any]) -> None:
    state = dict(merged.get("ai_drama_state") or {})
    for key in ("script", "storyboard", "assets", "asset_paths", "voice_plan", "shots", "edit"):
        if merged.get(key) is not None and key not in state:
            state[key] = merged[key]
    if "input" not in state:
        topic = merged.get("topic") or merged.get("content") or "一个日常里的异常"
        state["input"] = {"script": merged.get("script")} if merged.get("script") else {"theme": topic}
    pipeline.state = state


async def run_canvas_tool(tool_id: str, payload: dict[str, Any], upstream: dict[str, Any] | None = None) -> dict[str, Any]:
    merged = _merge(upstream, payload)
    out_dir = str(merged.get("out_dir") or "output/ai_drama/canvas")
    topic = str(merged.get("topic") or merged.get("content") or "一个日常里的异常")
    series = merged.get("series")
    series_dir = str(merged.get("series_dir") or "output/ai_drama/series")

    if tool_id in STAGE_TOOLS:
        from .pipeline import Pipeline

        series = series or (_default_series(topic, series_dir) if STAGE_TOOLS[tool_id] == "script" else None)
        pipeline = Pipeline(
            out_dir,
            episode_id=str(merged.get("episode_id") or merged.get("slate_id") or "canvas"),
            budget_cny=merged.get("budget_cny"),
            prefer_provider=merged.get("video_provider") or merged.get("provider"),
            seed=int(merged.get("seed") or 42),
            render_images=bool(merged.get("render_images", True)),
            lipsync=merged.get("lipsync"),
            series=series,
            gated=bool(merged.get("gated", False)),
            cost_gate=bool(merged.get("cost_gate", False)),
            edit_options=merged.get("edit_options") or {},
        )
        _seed_state(pipeline, merged)
        stage = STAGE_TOOLS[tool_id]
        fn = getattr(pipeline, f"stage_{'delivery' if stage == 'delivery' else stage}")
        check = getattr(pipeline, f"_check_{'delivery' if stage == 'delivery' else stage}", None)
        output = pipeline.run_node(stage, fn, check) if check is not None else fn()
        doc = pipeline.state
        if series is not None:
            doc["series"] = series
        return {
            "status": "ok",
            "tool_id": tool_id,
            "ai_drama_node": stage,
            "ai_drama_state": doc,
            "output": json.dumps(output, ensure_ascii=False)[:1200],
            **{k: v for k, v in output.items() if isinstance(v, (str, int, float, list, dict))},
            "series_dir": series_dir,
        }

    if tool_id == "drama.style_cards":
        from .style_cards import list_style_cards

        cards = list_style_cards()
        return {
            "status": "ok",
            "tool_id": tool_id,
            "style_cards": cards,
            "output": json.dumps(
                [{"id": c["id"], "name": c["name"], "available": c["available"]} for c in cards],
                ensure_ascii=False,
            ),
        }

    if tool_id == "drama.series_create":
        from .series import create_series, save_series

        series = series or _default_series(topic, series_dir)
        if merged.get("cast") or merged.get("series_title"):
            series = create_series(
                title=str(merged.get("series_title") or topic),
                genre=str(merged.get("genre") or "daily_anomaly"),
                cast=list(merged.get("cast") or series.get("cast") or []),
                out_dir=series_dir,
                style=str(merged.get("style") or "anime"),
                style_card=str(merged.get("style_card") or ""),
            )
        else:
            save_series(series, series_dir)
        return {"status": "ok", "tool_id": tool_id, "series": series, "series_dir": series_dir,
                "output": f"系列 {series.get('title')}：{len(series.get('cast') or [])} 个固定角色"}

    if tool_id == "drama.series_topics":
        from .topics import suggest_topics, topics_markdown

        series = series or _default_series(topic, series_dir)
        result = suggest_topics(series, pov=bool(merged.get("pov")), n=int(merged.get("n") or 3))
        return {"status": "ok" if result["passed"] else "failed", "tool_id": tool_id,
                "topics": result, "series": series, "series_dir": series_dir,
                "output": topics_markdown(result)}

    if tool_id == "drama.series_beats":
        from .beats import build_beats, revise_beat, validate_beats
        from .topics import suggest_topics

        series = series or _default_series(topic, series_dir)
        topics = merged.get("topics") or suggest_topics(series, pov=bool(merged.get("pov")))
        idea = merged.get("idea")
        if idea is None:
            idea = next((i for i in topics.get("ideas") or [] if i.get("id") == topics.get("recommended")),
                        (topics.get("ideas") or [{}])[0])
        pov = merged.get("pov")
        beats = merged.get("beats") or build_beats(idea, series.get("cast") or [],
                                                   pov=bool(pov if pov is not None else idea.get("pov")))
        if merged.get("revise"):
            beats = revise_beat(beats, int(merged["revise"].get("index") or 0),
                                dict(merged["revise"].get("patch") or {}))
        findings = validate_beats(beats, pov=bool(pov), lead_id=str((series.get("cast") or [{}])[0].get("id") or ""))
        return {"status": "ok" if not any(f["severity"] == "blocker" for f in findings) else "failed",
                "tool_id": tool_id, "beats": beats, "idea": idea, "topics": topics,
                "findings": findings, "series": series, "series_dir": series_dir,
                "output": json.dumps(beats, ensure_ascii=False)[:1200]}

    if tool_id == "drama.series_episode":
        from .series_pipeline import run_series_episode

        series = series or _default_series(topic, series_dir)
        if series and not Path(series_dir, "series.json").is_file():
            from .series import save_series

            save_series(series, series_dir)
        result = run_series_episode(
            series_dir,
            idea=merged.get("idea"),
            idea_id=merged.get("idea_id"),
            beats=merged.get("beats"),
            revise=merged.get("revise"),
            pov=merged.get("pov"),
            out_dir=merged.get("out_dir") or str(Path(out_dir) / "series_episode"),
            budget_cny=merged.get("budget_cny"),
            provider=merged.get("video_provider") or merged.get("provider"),
            render_images=bool(merged.get("render_images", True)),
            gated=bool(merged.get("gated", True)),
            lipsync=merged.get("lipsync"),
            translate_to=merged.get("translate_to"),
            glossary=merged.get("glossary") or {},
            trim=bool(merged.get("trim", True)),
            bgm=merged.get("bgm"),
            do_render=bool(merged.get("do_render", True)),
        )
        return {"status": "ok", "tool_id": tool_id, "series_episode": result,
                "series_dir": series_dir,
                "output": str((result.get("episode") or {}).get("deliverable") or result.get("out_dir"))}

    if tool_id == "drama.series_review":
        from .review import review_markdown
        from .series_pipeline import review_series

        result = review_series(series_dir, views=merged.get("views"))
        return {"status": "ok", "tool_id": tool_id, "review": result,
                "output": review_markdown(result)}

    raise ValueError(f"unknown ai_drama canvas tool: {tool_id}")
