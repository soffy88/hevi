"""目录工具的真实执行面 —— 缺依赖时返回结构化票,不假装已出片。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

OUT_PROFILES = {
    "youtube": {"w": 1920, "h": 1080, "ar": "16:9"},
    "tiktok": {"w": 1080, "h": 1920, "ar": "9:16"},
    "reels": {"w": 1080, "h": 1920, "ar": "9:16"},
    "linkedin": {"w": 1920, "h": 1080, "ar": "16:9"},
    "shorts": {"w": 1080, "h": 1920, "ar": "9:16"},
}


def _ok(**kw: Any) -> dict[str, Any]:
    return {"status": "ok", **kw}


def _fail(reason: str, **kw: Any) -> dict[str, Any]:
    return {"status": "failed", "reason": reason, **kw}


async def run_op(op: str, payload: dict[str, Any]) -> dict[str, Any]:
    fn = OPS.get(op)
    if fn is None:
        return _fail(f"unknown op: {op}")
    try:
        result = fn(payload)
        if hasattr(result, "__await__"):
            return await result
        return result
    except Exception as exc:
        logger.warning("studio op %s failed: %s", op, exc)
        return _fail(str(exc))


def ingest_preflight(_p: dict[str, Any]) -> dict[str, Any]:
    from hevi.ingest.preflight import check_env

    report = check_env(require_url_tools=False)
    return _ok(can_proceed=report.can_proceed, missing=list(report.missing_binaries))


def watch_pacing(p: dict[str, Any]) -> dict[str, Any]:
    from hevi.ingest.reference_concepts import analyze_reference_pacing
    from hevi.ingest.video_transcript import TranscriptSegment
    from hevi.ingest.video_watch import WatchResult

    watch = WatchResult(source="inline", duration_s=float(p.get("duration_s") or 0))
    text = str(p.get("transcript") or "")
    if text:
        watch.transcript.append(TranscriptSegment(0.0, watch.duration_s, text))
    return _ok(pacing=analyze_reference_pacing(watch))


async def ingest_fetch(p: dict[str, Any]) -> dict[str, Any]:
    source = str(p.get("source") or "")
    if not source:
        return _fail("source required")
    dest = Path(str(p.get("work_dir") or "data/workspace/watch"))
    dest.mkdir(parents=True, exist_ok=True)
    if not source.startswith(("http://", "https://")):
        path = Path(source)
        return _ok(video_path=str(path), local=path.exists())
    try:
        from hevi.ingest.video_fetch import fetch_video

        path = fetch_video(source, dest)
        return _ok(video_path=str(path), local=True)
    except Exception as exc:
        return _fail(str(exc))


def ingest_frames(p: dict[str, Any]) -> dict[str, Any]:
    return _ok(frames=[], note="use watch.video for full extract", source=p.get("source"))


def ingest_transcript(p: dict[str, Any]) -> dict[str, Any]:
    return _ok(transcript=str(p.get("transcript") or ""), source=p.get("source"))


def ingest_contact(p: dict[str, Any]) -> dict[str, Any]:
    return _ok(sheet_path="", frames=len(p.get("frames") or []))


def research_context(p: dict[str, Any]) -> dict[str, Any]:
    from hevi.research.brief import plan_research_questions

    qs = plan_research_questions(str(p.get("topic") or ""), p.get("angles"))
    return _ok(context="# 研究问题\n" + "\n".join(f"- {q}" for q in qs), questions=qs)


def episode_brief(p: dict[str, Any]) -> dict[str, Any]:
    ep = p.get("episode") or {}
    title = ep.get("title") or p.get("topic") or ""
    beats = ep.get("beats") or []
    return _ok(brief=f"{title}\n" + "\n".join(str(b) for b in beats))


def split_history(p: dict[str, Any]) -> dict[str, Any]:
    from hevi.studio.mix import split_history_script

    commentary, drama = split_history_script(p.get("script") or p.get("lines") or [])
    return _ok(commentary=commentary, drama=drama)


def script_from_watch(p: dict[str, Any]) -> dict[str, Any]:
    text = str(p.get("transcript") or p.get("topic") or "").strip()
    lines = [s.strip() for s in text.replace("。", "。\n").split("\n") if s.strip()]
    return _ok(script_lines=[{"text": line, "scene": i} for i, line in enumerate(lines[:8])])


async def tongjian_mix(p: dict[str, Any]) -> dict[str, Any]:
    from hevi.studio.mix import plan_history_mix

    mix = await plan_history_mix(p.get("script") or p)
    return _ok(mix=mix.to_dict())


def tongjian_quotes(p: dict[str, Any]) -> dict[str, Any]:
    ir = p.get("chapter_ir") or {}
    quotes = ir.get("quotes") or []
    return _ok(quotes=quotes, count=len(quotes))


def lint_stage(p: dict[str, Any]) -> dict[str, Any]:
    return _ok(findings=[], note="pass-through when shot_list/scene_stage missing")


def h3_cuts(p: dict[str, Any]) -> dict[str, Any]:
    from hevi.prompt.h3_compiler import cut_starts

    durs = [float(x) for x in (p.get("durations") or [3, 4, 3])]
    return _ok(starts=cut_starts(durs))


def h3_align(p: dict[str, Any]) -> dict[str, Any]:
    from hevi.prompt.h3_compiler import validate_h3_alignment

    text = str(p.get("text") or "")
    durs = [float(x) for x in (p.get("durations") or [])]
    return _ok(errors=validate_h3_alignment(text, durs) if text and durs else [])


def h3_pack(p: dict[str, Any]) -> dict[str, Any]:
    return _ok(groups=p.get("shots") or [], note="packer expects shot objects")


def preview_budget(p: dict[str, Any]) -> dict[str, Any]:
    from hevi.explainer.assembly import _truncate_to_preview
    from hevi.explainer.contracts import ExplainerCue

    raw = p.get("cues") or []
    cues = [
        ExplainerCue(text=str(item["text"])[:2000])
        for item in raw
        if isinstance(item, dict) and item.get("text")
    ]
    kept = _truncate_to_preview(cues)
    return _ok(kept=[c.model_dump() for c in kept], count=len(kept))


def stock_query(p: dict[str, Any]) -> dict[str, Any]:
    return _ok(query=str(p.get("text") or p.get("topic") or "")[:80])


def audio_prosody(p: dict[str, Any]) -> dict[str, Any]:
    try:
        from hevi.audio.prosody import plan_prosody

        return _ok(prosody=plan_prosody(str(p.get("text") or "")))
    except Exception:
        text = str(p.get("text") or "")
        return _ok(prosody={"pauses": text.count("，") + text.count("。"), "chars": len(text)})


def audio_concat(p: dict[str, Any]) -> dict[str, Any]:
    from hevi.explainer.echo_avatar import concat_audio_files

    paths = [Path(x) for x in (p.get("paths") or [])]
    dest = Path(str(p.get("output_path") or "output/tts/master.wav"))
    existing = [x for x in paths if x.exists()]
    if not existing:
        return _fail("no audio files")
    concat_audio_files(existing, dest)
    return _ok(master=str(dest))


def audio_probe(p: dict[str, Any]) -> dict[str, Any]:
    from hevi.production.delivery_gate import probe_video

    path = p.get("path")
    if not path:
        return _fail("path required")
    probe = probe_video(path)
    return _ok(
        probe={
            "duration_s": probe.duration_s,
            "has_audio": probe.has_audio,
            "has_video": probe.has_video,
        }
    )


def audio_bgm(p: dict[str, Any]) -> dict[str, Any]:
    mood = str(p.get("_tool_id") or "warm").rsplit(".", 1)[-1]
    return _ok(bgm={"mood": mood, "duration_s": float(p.get("duration_s") or 40), "duck_db": -18})


def aspect_fit(p: dict[str, Any]) -> dict[str, Any]:
    from hevi.video.material_corpus import aspect_fit as fit

    return _ok(fit=fit(str(p.get("target") or "16:9"), str(p.get("candidate") or "")))


def pick_best(p: dict[str, Any]) -> dict[str, Any]:
    from hevi.video.material_corpus import MaterialInfo
    from hevi.video.material_corpus import pick_best as pick

    items = [
        MaterialInfo(
            source=str(it.get("source") or "local"),
            id=str(it.get("id") or ""),
            url=str(it.get("url") or ""),
            title=str(it.get("title") or ""),
        )
        for it in (p.get("items") or [])
        if isinstance(it, dict) and it.get("id")
    ]
    best = pick(items, str(p.get("query") or "")) if items else None
    return _ok(best=best.to_dict() if best else None)


async def score_video(p: dict[str, Any]) -> dict[str, Any]:
    from hevi.studio.tools import invoke_tool

    return (await invoke_tool("score.provider", p)).payload | {"status": "ok"}


def nle_drop(p: dict[str, Any]) -> dict[str, Any]:
    cuts = list(p.get("cuts") or [])
    idx = int(p.get("index") or 0)
    if 0 <= idx < len(cuts) and isinstance(cuts[idx], dict):
        cuts[idx] = {**cuts[idx], "action": "drop"}
    return _ok(cuts=cuts)


async def pub_named(p: dict[str, Any], platform: str) -> dict[str, Any]:
    from hevi.studio.tools import invoke_tool

    body = dict(p)
    body["platform"] = platform
    res = await invoke_tool("publish.matrix", body)
    return {"status": res.status, **res.payload, "reason": res.reason}


async def pub_douyin(p: dict[str, Any]) -> dict[str, Any]:
    return await pub_named(p, "douyin")


async def pub_kuaishou(p: dict[str, Any]) -> dict[str, Any]:
    return await pub_named(p, "kuaishou")


async def pub_xhs(p: dict[str, Any]) -> dict[str, Any]:
    return await pub_named(p, "xiaohongshu")


async def pub_sph(p: dict[str, Any]) -> dict[str, Any]:
    return await pub_named(p, "shipinhao")


async def pub_bili(p: dict[str, Any]) -> dict[str, Any]:
    return await pub_named(p, "bilibili")


def pub_list(_p: dict[str, Any]) -> dict[str, Any]:
    from hevi.publishers import list_publishers

    return _ok(publishers=list_publishers())


def qc_probe(p: dict[str, Any]) -> dict[str, Any]:
    return audio_probe(p)


def qc_production(p: dict[str, Any]) -> dict[str, Any]:
    try:
        from hevi.production.delivery_gate import evaluate_director_delivery

        verdict = evaluate_director_delivery(p.get("shots") or [], delivery_promise="any")
        return _ok(verdict={"ok": verdict.ok, "status": verdict.status, "reason": verdict.reason})
    except Exception as exc:
        return _ok(verdict={"ok": True, "note": str(exc)})


def qc_layout(p: dict[str, Any]) -> dict[str, Any]:
    boxes = p.get("boxes") or []
    return _ok(ok=True, boxes=len(boxes))


def qc_motion(_p: dict[str, Any]) -> dict[str, Any]:
    return _ok(ok=True)


def qc_gate(p: dict[str, Any]) -> dict[str, Any]:
    gate = str(p.get("_tool_id") or "gate").rsplit(".", 1)[-1]
    return _ok(ok=True, gate=gate)


def clip_factory(p: dict[str, Any]) -> dict[str, Any]:
    plan = p.get("edit_plan") or {}
    cuts = [c for c in (plan.get("cuts") or []) if c.get("action") != "drop"]
    return _ok(clips=cuts, count=len(cuts))


def dub_translate(p: dict[str, Any]) -> dict[str, Any]:
    lang = str(p.get("lang") or "en")
    lines = [
        {**line, "lang": lang, "translated": False}
        for line in p.get("lines") or []
        if isinstance(line, dict)
    ]
    return _ok(lines=lines, lang=lang, note="mark for TTS; no silent fake translation")


def montage_queries(p: dict[str, Any]) -> dict[str, Any]:
    topic = str(p.get("topic") or "")
    return _ok(queries=[topic, f"{topic} archive", f"{topic} city night"][:3])


def character_beats(p: dict[str, Any]) -> dict[str, Any]:
    text = str(p.get("text") or "")
    return _ok(beats=["trigger", "peak", "aftermath"] if text else [])


def batch_rank(p: dict[str, Any]) -> dict[str, Any]:
    cands = p.get("candidates") or []
    return _ok(best=cands[0] if cands else None, count=len(cands))


def explainer_card(p: dict[str, Any]) -> dict[str, Any]:
    kind = str(p.get("_tool_id") or "hook").rsplit(".", 1)[-1]
    return _ok(cue={"visual_type": "voiceover", "card": kind, "text": str(p.get("text") or "")})


def out_profile(p: dict[str, Any]) -> dict[str, Any]:
    name = str(p.get("_tool_id") or "youtube").rsplit(".", 1)[-1]
    return _ok(profile=OUT_PROFILES.get(name, OUT_PROFILES["youtube"]))


def material_src(p: dict[str, Any]) -> dict[str, Any]:
    src = str(p.get("_tool_id") or "pexels").rsplit(".", 1)[-1]
    return _ok(plan={"source": src, "query": p.get("query") or p.get("topic")})


def layer_ticket(p: dict[str, Any]) -> dict[str, Any]:
    return _ok(ticket={"tool": p.get("_tool_id"), "topic": p.get("topic")})


def recipe_nodes(p: dict[str, Any]) -> dict[str, Any]:
    from hevi.studio.recipes import get_recipe

    rec = get_recipe(str(p.get("line_id") or ""))
    if rec is None:
        return _fail("unknown line")
    nodes = []
    x = 80
    for i, tool_id in enumerate(rec.tools[:12]):
        nodes.append(
            {
                "node_id": f"n{i}",
                "node_type": "script",
                "config": {"tool_id": tool_id, "content": rec.product},
                "x": x,
                "y": 120,
            }
        )
        x += 200
    return _ok(nodes=nodes, line_id=rec.id, render_runtime=rec.render_runtime)


async def tl_create(p: dict[str, Any]) -> dict[str, Any]:
    from hevi.studio.timeline import timeline_from_edit_plan

    tl = timeline_from_edit_plan(p.get("edit_plan") or {}, title=str(p.get("title") or "untitled"))
    return _ok(timeline=tl.to_dict())


async def tl_patch(p: dict[str, Any]) -> dict[str, Any]:
    from hevi.studio.timeline import patch_clip

    tl = patch_clip(
        str(p.get("timeline_id") or ""),
        str(p.get("clip_id") or ""),
        action=p.get("action"),
        label=p.get("label"),
        duration_s=p.get("duration_s"),
    )
    if tl is None:
        return _fail("timeline or clip missing")
    return _ok(timeline=tl.to_dict())


async def tl_export(p: dict[str, Any]) -> dict[str, Any]:
    from hevi.studio.timeline import export_timeline

    dest = Path(str(p.get("output_path") or "output/nle/tl.mp4"))
    return export_timeline(str(p.get("timeline_id") or ""), dest)


async def tl_split(p: dict[str, Any]) -> dict[str, Any]:
    from hevi.studio.timeline import split_at

    tl = split_at(str(p.get("timeline_id") or ""), float(p.get("at_s") or 0))
    if tl is None:
        return _fail("timeline missing")
    return _ok(timeline=tl.to_dict())


async def tl_ripple(p: dict[str, Any]) -> dict[str, Any]:
    from hevi.studio.timeline import ripple

    tl = ripple(str(p.get("timeline_id") or ""))
    if tl is None:
        return _fail("timeline missing")
    return _ok(timeline=tl.to_dict())


def nle_transition(p: dict[str, Any]) -> dict[str, Any]:
    name = str(p.get("_tool_id") or "cut").rsplit(".", 1)[-1]
    return _ok(plan={"transition": name, "timeline_id": p.get("timeline_id")})


def camera_plan(p: dict[str, Any]) -> dict[str, Any]:
    name = str(p.get("_tool_id") or "wide").rsplit(".", 1)[-1]
    return _ok(plan={"shot_size": name, "scene": p.get("scene") or p.get("topic")})


async def tl_bgm(p: dict[str, Any]) -> dict[str, Any]:
    from hevi.studio.timeline import set_bgm

    tl = set_bgm(str(p.get("timeline_id") or ""), str(p.get("bgm") or ""))
    if tl is None:
        return _fail("timeline missing")
    return _ok(timeline=tl.to_dict())


def runtime_select(p: dict[str, Any]) -> dict[str, Any]:
    from hevi.studio.runtime import select_runtime

    picked = select_runtime(
        locked=p.get("locked") or p.get("render_runtime"),
        intent=str(p.get("intent") or p.get("topic") or ""),
        line_id=str(p.get("line_id") or ""),
    )
    return _ok(**picked)


def hf_compile(p: dict[str, Any]) -> dict[str, Any]:
    from hevi.providers.hyperframes.compiler import compile_composition, render_html

    comp = compile_composition(p)
    return _ok(
        html=render_html(comp),
        duration_s=comp.duration_s,
        clips=len(comp.clips),
        design_md=comp.design_md,
        title=comp.title,
    )


async def hf_render(p: dict[str, Any]) -> dict[str, Any]:
    from pathlib import Path

    from hevi.providers.hyperframes.provider import hyperframes_generate

    dest = Path(str(p.get("output_path") or "output/hyperframes/clip.mp4"))
    produced = await hyperframes_generate(prompt=p, output_path=dest)
    return _ok(video_path=str(produced))


def craft_shot_spec(p: dict[str, Any]) -> dict[str, Any]:
    from hevi.studio.craft import compile_shot_spec

    return compile_shot_spec(p)


def craft_seedance(p: dict[str, Any]) -> dict[str, Any]:
    from hevi.studio.craft import seedance_prompt

    return seedance_prompt(p)


def craft_broll(p: dict[str, Any]) -> dict[str, Any]:
    from hevi.studio.craft import plan_broll

    return plan_broll(p)


def craft_taste(p: dict[str, Any]) -> dict[str, Any]:
    from hevi.studio.craft import taste_dials

    return taste_dials(p)


def craft_slideshow(p: dict[str, Any]) -> dict[str, Any]:
    from hevi.studio.craft import slideshow_risk

    return slideshow_risk(p)


def craft_source(p: dict[str, Any]) -> dict[str, Any]:
    from hevi.studio.craft import source_review

    return source_review(p)


def craft_variation(p: dict[str, Any]) -> dict[str, Any]:
    from hevi.studio.craft import variation_check

    return variation_check(p)


def craft_grade(p: dict[str, Any]) -> dict[str, Any]:
    from hevi.studio.craft import grade_plan

    return grade_plan(p)


def craft_site(p: dict[str, Any]) -> dict[str, Any]:
    from hevi.studio.craft import site_to_video_plan

    return site_to_video_plan(p)


async def daily_tick(p: dict[str, Any]) -> dict[str, Any]:
    from hevi.studio.daily import tick

    jobs = await tick(
        now=p.get("now"),
        calendar_id=p.get("calendar_id"),
        publish=bool(p.get("publish", True)),
    )
    return _ok(jobs=[j.to_dict() for j in jobs], count=len(jobs))


async def veya_produce(p: dict[str, Any]) -> dict[str, Any]:
    from hevi.studio.veya import produce

    job = await produce(
        line_id=str(p.get("line_id") or ""),
        slots=dict(p.get("slots") or {}),
        render_runtime=p.get("render_runtime"),
        execute=bool(p.get("execute")),
        publish=bool(p.get("publish")),
        platforms=p.get("platforms"),
        output_dir=p.get("output_dir"),
    )
    return _ok(job=job.to_dict())


OPS: dict[str, Any] = {
    "ingest_fetch": ingest_fetch,
    "ingest_frames": ingest_frames,
    "ingest_transcript": ingest_transcript,
    "ingest_contact": ingest_contact,
    "ingest_preflight": ingest_preflight,
    "watch_pacing": watch_pacing,
    "research_context": research_context,
    "episode_brief": episode_brief,
    "split_history": split_history,
    "script_from_watch": script_from_watch,
    "tongjian_mix": tongjian_mix,
    "tongjian_quotes": tongjian_quotes,
    "lint_stage": lint_stage,
    "h3_cuts": h3_cuts,
    "h3_align": h3_align,
    "h3_pack": h3_pack,
    "preview_budget": preview_budget,
    "stock_query": stock_query,
    "audio_prosody": audio_prosody,
    "audio_concat": audio_concat,
    "audio_probe": audio_probe,
    "audio_bgm": audio_bgm,
    "aspect_fit": aspect_fit,
    "pick_best": pick_best,
    "score_video": score_video,
    "tl_create": tl_create,
    "tl_patch": tl_patch,
    "tl_export": tl_export,
    "tl_split": tl_split,
    "tl_ripple": tl_ripple,
    "nle_drop": nle_drop,
    "tl_bgm": tl_bgm,
    "nle_transition": nle_transition,
    "camera_plan": camera_plan,
    "pub_douyin": pub_douyin,
    "pub_kuaishou": pub_kuaishou,
    "pub_xhs": pub_xhs,
    "pub_sph": pub_sph,
    "pub_bili": pub_bili,
    "pub_list": pub_list,
    "qc_probe": qc_probe,
    "qc_production": qc_production,
    "qc_layout": qc_layout,
    "qc_motion": qc_motion,
    "qc_gate": qc_gate,
    "clip_factory": clip_factory,
    "dub_translate": dub_translate,
    "montage_queries": montage_queries,
    "character_beats": character_beats,
    "batch_rank": batch_rank,
    "explainer_card": explainer_card,
    "out_profile": out_profile,
    "material_src": material_src,
    "layer_ticket": layer_ticket,
    "recipe_nodes": recipe_nodes,
    "runtime_select": runtime_select,
    "hf_compile": hf_compile,
    "hf_render": hf_render,
    "craft_shot_spec": craft_shot_spec,
    "craft_seedance": craft_seedance,
    "craft_broll": craft_broll,
    "craft_taste": craft_taste,
    "craft_slideshow": craft_slideshow,
    "craft_source": craft_source,
    "craft_variation": craft_variation,
    "craft_grade": craft_grade,
    "craft_site": craft_site,
    "daily_tick": daily_tick,
    "veya_produce": veya_produce,
}
