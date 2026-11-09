"""Series episode orchestration: topic -> beats -> gated render -> review."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .beats import beats_to_script, build_beats, revise_beat, validate_beats
from .pipeline import Pipeline
from .review import review_episodes
from .series import add_episode, load_series, save_series
from .topics import suggest_topics


def _pick_idea(topics: dict[str, Any], idea_id: str | None = None) -> dict[str, Any]:
    if idea_id:
        for idea in topics.get("ideas") or []:
            if idea.get("id") == idea_id:
                return idea
        raise ValueError(f"unknown idea id: {idea_id}")
    for idea in topics.get("ideas") or []:
        if idea.get("id") == topics.get("recommended"):
            return idea
    return (topics.get("ideas") or [{}])[0]


def prepare_episode(
    series: dict[str, Any],
    *,
    idea: dict[str, Any] | None = None,
    idea_id: str | None = None,
    beats: list[dict[str, Any]] | None = None,
    revise: dict[str, Any] | None = None,
    pov: bool | None = None,
) -> dict[str, Any]:
    topics = suggest_topics(series, pov=bool(pov))
    chosen = idea or _pick_idea(topics, idea_id)
    if pov is None:
        pov = bool(chosen.get("pov"))
    beat_list = beats or build_beats(chosen, series.get("cast") or [], pov=pov)
    if revise:
        beat_list = revise_beat(beat_list, int(revise.get("index") or 0), dict(revise.get("patch") or {}))
    pov = bool(pov)
    findings = validate_beats(beat_list, pov=pov, lead_id=str((series.get("cast") or [{}])[0].get("id") or ""))
    script = beats_to_script(chosen, beat_list, series.get("cast") or [], style=str(series.get("style") or "anime"), pov=pov)
    return {
        "topics": topics,
        "idea": chosen,
        "beats": beat_list,
        "beat_findings": findings,
        "script": script,
        "pov": pov,
    }


def run_series_episode(
    series_dir: str | Path,
    *,
    idea: dict[str, Any] | None = None,
    idea_id: str | None = None,
    beats: list[dict[str, Any]] | None = None,
    revise: dict[str, Any] | None = None,
    pov: bool | None = None,
    out_dir: str | Path | None = None,
    budget_cny: float | None = None,
    provider: str | None = None,
    render_images: bool = True,
    gated: bool = True,
    lipsync: bool | None = None,
    translate_to: str | None = None,
    glossary: dict[str, str] | None = None,
    llm: Any = None,
    trim: bool = True,
    bgm: dict[str, Any] | None = None,
    do_render: bool = True,
) -> dict[str, Any]:
    series = load_series(series_dir)
    prepared = prepare_episode(series, idea=idea, idea_id=idea_id, beats=beats, revise=revise, pov=pov)
    if prepared["beat_findings"] and any(f["severity"] == "blocker" for f in prepared["beat_findings"]):
        raise ValueError(f"节拍自检失败: {prepared['beat_findings']}")
    script = prepared["script"]
    if bgm:
        script["bgm"] = dict(bgm)
        script["bgm_allowed"] = True
    episode_no = len(series.get("episodes") or []) + 1
    out = Path(out_dir or (Path(series_dir) / "episodes" / f"ep{episode_no:02d}"))
    if not do_render:
        return {"series": series, **prepared, "out_dir": str(out), "rendered": False}

    pipeline = Pipeline(
        out,
        episode_id=f"{series.get('series_id')}_ep{episode_no:02d}",
        budget_cny=budget_cny,
        prefer_provider=provider,
        render_images=render_images,
        lipsync=lipsync,
        series=series,
        gated=gated,
        cost_gate=True,
        edit_options={
            "translate_to": translate_to,
            "glossary": glossary or {},
            "llm": llm,
            "trim": trim,
            "bgm": bgm,
        },
    )
    report = pipeline.run({"script": script})
    episode = {
        "episode_no": episode_no,
        "title": script.get("title"),
        "genre": prepared["idea"].get("genre"),
        "genre_label": prepared["idea"].get("genre_label"),
        "idea": prepared["idea"],
        "beats": prepared["beats"],
        "pov": prepared["pov"],
        "out_dir": str(out),
        "deliverable": report.get("delivery", {}).get("deliverable"),
        "duration_s": report.get("delivery", {}).get("duration_s"),
        "consistency": report.get("consistency"),
        "cost_plan": report.get("cost_plan"),
        "segment_gate": report.get("segment_gate"),
    }
    add_episode(series, episode)
    save_series(series, series_dir)
    return {
        "series": series,
        "episode": episode,
        "out_dir": str(out),
        "rendered": True,
        "report": report,
    }


def review_series(series_dir: str | Path, *, views: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    series = load_series(series_dir)
    episodes = list(series.get("episodes") or [])
    if views:
        by_no = {int(v.get("episode_no") or 0): v for v in views}
        for ep in episodes:
            update = by_no.get(int(ep.get("episode_no") or 0))
            if update:
                ep["views"] = update.get("views", ep.get("views", 0))
    report = review_episodes(series, episodes)
    (Path(series_dir) / "review.json").write_text(
        __import__("json").dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
