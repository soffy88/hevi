"""The 11 zero-cost line producers (omodul layer: TTS/stock/ffmpeg orchestration).

Each producer takes a validated ``ZeroLineRequest`` + a scratch dir and returns
``{"finals": [Path, ...], "provenance": [...], "notes": str, "artifacts": {...}}``.
All creative content (narration, b-roll queries, labels, source media) comes
from the request; producers never invent copy or substitute assets.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

from hevi.layer4_legacy.zerolines.omodul_impl._media import (
    FFMPEG,
    ZeroMediaError,
    dur,
    finish,
    frames_to_video,
    mix,
    pexels,
    rms_envelope,
    sh,
    shot,
    still_shot,
    subtitles_filter,
    topic_still,
    translate_text,
    tts,
    tts_lines,
    whisper_segments,
    write_bgm,
    xfade_concat,
)
from hevi.layer4_legacy.zerolines.oprim_impl.specs import (
    ZeroLineRequest,
    generate_broll_queries,
    generate_script_lines,
    spec_for,
)
from hevi.layer4_legacy.zerolines.oskill_impl import puppets
from hevi.layer4_legacy.zerolines.oskill_impl.audio_math import mouth_series
from hevi.layer4_legacy.zerolines.oskill_impl.captions import (
    build_ass,
    caption_events,
    kinetic_events,
    kinetic_words,
    word_chunks,
)
from hevi.layer4_legacy.zerolines.oskill_impl.shots import (
    CAVEMAN_SECONDS,
    DEFAULT_MOVES,
    director_shot_list,
    narration_shot_lengths,
    pick_windows,
    place_on_beats,
)

Result = dict[str, Any]
PIPER_PROV = {"source": "piper local TTS (CPU)", "licence": "MIT engine; voice per model card"}
BGM_PROV = {"source": "procedural BGM (hevi zerolines audio_math.synth_bgm)", "licence": "own"}


def _prov(src: dict[str, Any], used_for: str) -> dict[str, Any]:
    return {k: v for k, v in src.items() if k != "path"} | {"used_for": used_for}


def _write_ass(path: Path, W: int, H: int, events: list) -> Path:
    path.write_text(build_ass(width=W, height=H, events=events), encoding="utf-8")
    return path


def _orient(W: int, H: int) -> str:
    return "portrait" if H > W else "landscape"


def _fit_lengths(lengths: list[float], xd: float, target: float = 30.0) -> list[float]:
    """Grow the final shot so the assembled film reaches the 30 s product length.

    The clip is stream-looped by ``shot`` when the source is shorter, so the
    extra time keeps the camera move alive instead of freezing the last frame.
    """
    if not lengths:
        return lengths
    span = sum(lengths) - xd * (len(lengths) - 1)
    if span < target:
        lengths = list(lengths)
        lengths[-1] += target - span
    return lengths


_ARCHIVAL_KEYS = (
    "mural", "ancient", "dynasty", "history", "historic", "museum",
    "archive", "cave", "temple", "traditional", "cultural", "art",
)


def _stills_args(req: ZeroLineRequest) -> tuple[str, int]:
    """Commons stills for historical/art topics (thin stock video), else none."""
    subject = str(req.extras.get("subject_hint") or req.topic or "").lower()
    if any(k in subject for k in _ARCHIVAL_KEYS):
        return (req.topic or (req.texts[0] if req.texts else "")), 1
    return "", 0


def _broll_film(req: ZeroLineRequest, tmp: Path, W: int, H: int, *, moves=None, grade: str = "", mood: str = "warm",
                speed: float = 1.0, xd: float = 0.5, stills_query: str = "", still_every: int = 3):
    """Narration line i is covered by stock shot i (shot length = line length).

    ``stills_query`` mixes free Wikimedia Commons stills (Ken Burns) into the
    film: every ``still_every``th shot when >0.  Commons covers historical/art
    subjects that stock video does not, so the film stays on-topic instead of
    falling back to unrelated clips.
    """
    vo, cues = tts_lines(list(req.texts), tmp / "vo", lang=req.lang, speed=speed)
    used: set[int] = set()
    used_titles: set[str] = set()
    shots, prov = [], []
    lengths = _fit_lengths(narration_shot_lengths(cues, xd=xd), xd)
    total = sum(lengths) - xd * (len(lengths) - 1)
    orient = _orient(W, H)
    for i, (seg, q) in enumerate(zip(lengths, req.queries, strict=False)):
        mv = (moves or DEFAULT_MOVES)[i % len(moves or DEFAULT_MOVES)]
        if stills_query and still_every > 0 and i % still_every == 0:
            try:
                img = topic_still(stills_query, width=max(W, H), exclude=used_titles)
                prov.append({"source": img.get("source", "topic_still"), "query": stills_query,
                             "title": img.get("title", ""), "author": img.get("author", ""),
                             "licence": img.get("licence", ""), "page": img.get("page", ""),
                             "used_for": f"shot {i + 1}"})
                shots.append(still_shot(img["path"], tmp / f"s{i}.mp4", seg, W, H, move=mv, grade=grade))
                continue
            except Exception:
                pass  # thin Commons coverage: fall back to stock video
        try:
            src = pexels(q, orientation=orient, min_d=4, exclude=used)
            prov.append(_prov(src, f"shot {i + 1}"))
            shots.append(shot(src["path"], tmp / f"s{i}.mp4", seg, W, H, move=mv, grade=grade))
        except Exception:
            # Thin/no stock for this query: keep the film on-topic with a still
            # instead of dropping the shot or failing the whole render.
            img = topic_still(stills_query or q, width=max(W, H), exclude=used_titles)
            prov.append({"source": img.get("source", "topic_still"), "query": stills_query or q,
                         "title": img.get("title", ""), "author": img.get("author", ""),
                         "licence": img.get("licence", ""), "used_for": f"shot {i + 1}"})
            shots.append(still_shot(img["path"], tmp / f"s{i}.mp4", seg, W, H, move=mv, grade=grade))
    film = xfade_concat(shots, tmp / "film.mp4", xd)
    audio = mix(vo, write_bgm(tmp / "bgm.wav", total + 1, mood), tmp / "mix.wav", total)
    return film, audio, cues, prov, total


def _title(req: ZeroLineRequest) -> str:
    return (req.title or "").strip()


# ---------------------------------------------------------------- b-roll family
def kinetic_promo(req: ZeroLineRequest, d: Path) -> Result:
    sp = spec_for(req.line_id)
    W, H, tmp = sp.width, sp.height, d / "tmp"
    vo, cues = tts_lines(list(req.texts), tmp / "vo", lang=req.lang, speed=1.05)
    total = max(30.0, dur(vo) + 1.5)
    used: set[int] = set()
    seg = total / len(req.queries) + 0.4
    shots, prov = [], []
    orient = _orient(W, H)
    stills_query, still_every = _stills_args(req)
    used_titles: set[str] = set()
    for i, q in enumerate(req.queries):
        if stills_query and still_every > 0 and i % still_every == 0:
            try:
                img = topic_still(stills_query, width=max(W, H), exclude=used_titles)
                prov.append({"source": img.get("source", "topic_still"), "query": stills_query,
                             "title": img.get("title", ""), "author": img.get("author", ""),
                             "licence": img.get("licence", ""), "used_for": f"shot {i + 1}"})
                shots.append(still_shot(img["path"], tmp / f"s{i}.mp4", seg, W, H,
                                        move=DEFAULT_MOVES[i % 4],
                                        grade="eq=brightness=-0.04:saturation=1.15"))
                continue
            except Exception:
                pass
        s = pexels(q, orientation=orient, min_d=4, exclude=used)
        prov.append(_prov(s, f"shot {i + 1}"))
        shots.append(shot(s["path"], tmp / f"s{i}.mp4", seg, W, H, move=DEFAULT_MOVES[i % 4],
                          grade="eq=brightness=-0.04:saturation=1.15"))
    film = xfade_concat(shots, tmp / "film.mp4", 0.4, "slideleft")
    ev = kinetic_events(words=kinetic_words(list(req.texts)), cues=cues, total=total, width=W, height=H)
    cta = str(req.extras.get("cta") or _title(req))
    if cta:
        ev.append((total - 2.4, total, "Kicker", r"{\an2\fad(300,0)\fs34}" + cta))
    ass = _write_ass(tmp / "k.ass", W, H, ev)
    audio = mix(vo, write_bgm(tmp / "bgm.wav", total + 1, "bright"), tmp / "mix.wav", total, -14)
    final = finish(film, audio, d / f"{req.line_id}.mp4", ass)
    return {"finals": [final], "provenance": [*prov, PIPER_PROV, BGM_PROV],
            "notes": "per-clause kinetic typography timed to narration character offsets"}


def explainer(req: ZeroLineRequest, d: Path) -> Result:
    sp = spec_for(req.line_id)
    W, H, tmp = sp.width, sp.height, d / "tmp"
    extras = getattr(req, "extras", {}) or {}
    grade_map = {"bright": "eq=contrast=1.05:saturation=1.2", "dark": "eq=contrast=1.1:saturation=0.8", "normal": "eq=saturation=1.1"}
    grade = grade_map.get(str(extras.get("grade", "normal")), "eq=saturation=1.1")
    speed = float(extras.get("speed", 1.0))
    xd = float(extras.get("xd", 0.5))
    # executable params from judge feedback
    if isinstance(extras.get("material_keywords"), list) and extras["material_keywords"]:
        req = ZeroLineRequest(**{**req.to_dict(), "queries": tuple(extras["material_keywords"])})
    if isinstance(extras.get("script_rewrite"), str) and extras["script_rewrite"]:
        req = ZeroLineRequest(**{**req.to_dict(), "texts": (extras["script_rewrite"],)})
    # Historical/art subjects are thin on stock video but deep on Commons;
    # modern subjects keep the livelier Pexels video.
    stills_query, still_every = _stills_args(req)
    film, audio, cues, prov, _ = _broll_film(
        req, tmp, W, H, grade=grade, speed=speed, xd=xd,
        stills_query=stills_query, still_every=still_every,
    )
    ev = caption_events(cues)
    for (a, b, _), h in zip(cues, req.labels, strict=False):
        if h:
            ev.append((a, b, "Lower", r"{\an7\pos(70,90)\fad(200,200)\fs52\c&H00C8FF&}" + h))
    if _title(req):
        ev.insert(0, (0.1, cues[0][1], "Title", r"{\fad(300,300)}" + _title(req)))
    ass = _write_ass(tmp / "e.ass", W, H, ev)
    final = finish(film, audio, d / f"{req.line_id}.mp4", ass)
    return {"finals": [final], "provenance": [*prov, PIPER_PROV, BGM_PROV], "notes": "one stock shot per point + headings"}


def cinematic(req: ZeroLineRequest, d: Path) -> Result:
    sp = spec_for(req.line_id)
    W, H, tmp = sp.width, sp.height, d / "tmp"
    extras = getattr(req, "extras", {}) or {}
    grade = "eq=contrast=1.12:saturation=0.85:gamma=0.95,colorbalance=rs=0.08:bs=-0.06:rh=0.05:bh=-0.05"
    if str(extras.get("grade", "")).lower() == "bright":
        grade = "eq=contrast=1.05:saturation=1.15:gamma=1.0,colorbalance=rs=0.02:bs=0.02"
    speed = float(extras.get("speed", 0.92))
    xd = float(extras.get("xd", 0.5))
    if isinstance(extras.get("material_keywords"), list) and extras["material_keywords"]:
        req = ZeroLineRequest(**{**req.to_dict(), "queries": tuple(extras["material_keywords"])})
    if isinstance(extras.get("script_rewrite"), str) and extras["script_rewrite"]:
        req = ZeroLineRequest(**{**req.to_dict(), "texts": (extras["script_rewrite"],)})
    stills_query, still_every = _stills_args(req)
    film, audio, cues, prov, _ = _broll_film(req, tmp, W, H, moves=("push", "pan_r", "push", "pull", "pan_l"),
                                             grade=grade, speed=speed, xd=xd,
                                             stills_query=stills_query, still_every=still_every)
    ev = caption_events(cues)
    if _title(req):
        ev = [(0.2, 3.2, "Title", r"{\fad(400,400)\blur1}" + _title(req)), *ev]
    bar = int(H * 0.12)
    extra = (f"drawbox=x=0:y=0:w=iw:h={bar}:color=black:t=fill,"
             f"drawbox=x=0:y=ih-{bar}:w=iw:h={bar}:color=black:t=fill")
    ass = _write_ass(tmp / "c.ass", W, H, ev)
    final = finish(film, audio, d / f"{req.line_id}.mp4", ass, extra)
    return {"finals": [final], "provenance": [*prov, PIPER_PROV, BGM_PROV], "notes": "graded 2.35-style letterbox film"}


def director_pipeline(req: ZeroLineRequest, d: Path) -> Result:
    sp = spec_for(req.line_id)
    W, H, tmp = sp.width, sp.height, d / "tmp"
    plan = director_shot_list(texts=list(req.texts), queries=list(req.queries),
                              overrides=req.extras.get("shot_overrides"))
    shot_list = d / "shot_list.json"
    shot_list.write_text(json.dumps({"brief": {"title": _title(req), "topic": req.topic}, "shot_list": plan},
                                    ensure_ascii=False, indent=2), encoding="utf-8")
    driven = ZeroLineRequest(**{**req.to_dict(), "queries": tuple(s["query"] for s in plan),
                                "texts": tuple(s["narration"] for s in plan)})
    stills_query, still_every = _stills_args(req)
    film, audio, cues, prov, _ = _broll_film(driven, tmp, W, H, moves=tuple(s["camera"] for s in plan),
                                             mood="bright", stills_query=stills_query, still_every=still_every)
    ev = caption_events(cues)
    if _title(req):
        ev = [(0.2, 3.0, "Title", r"{\fad(400,400)}" + _title(req)), *ev]
    ass = _write_ass(tmp / "dp.ass", W, H, ev)
    final = finish(film, audio, d / f"{req.line_id}.mp4", ass)
    return {"finals": [final], "provenance": [*prov, PIPER_PROV, BGM_PROV],
            "notes": "shot_list.json is the director output that drove the assembly",
            "artifacts": {"shot_list": str(shot_list)}}


def history_scene(req: ZeroLineRequest, d: Path) -> Result:
    sp = spec_for(req.line_id)
    W, H, tmp = sp.width, sp.height, d / "tmp"
    film, audio, cues, prov, _ = _broll_film(req, tmp, W, H, moves=("pull", "pan_r", "push", "push", "pan_l", "pull"),
                                             grade="eq=saturation=0.8,colorbalance=rs=0.06:bs=-0.05",
                                             stills_query=req.topic or (req.texts[0] if req.texts else ""),
                                             still_every=1)
    ev = caption_events(cues) + [
        (a, b, "Lower", r"{\an7\pos(70,80)\fad(250,250)\fs56\c&H7FD7FF&}" + y)
        for (a, b, _), y in zip(cues, req.labels, strict=False) if y
    ]
    if _title(req):
        ev = [(0.2, 3.4, "Title", r"{\fad(400,400)}" + _title(req)), *ev]
    ass = _write_ass(tmp / "h.ass", W, H, ev)
    final = finish(film, audio, d / f"{req.line_id}.mp4", ass)
    return {"finals": [final], "provenance": [*prov, PIPER_PROV, BGM_PROV], "notes": "archival grade + year lower-thirds"}


# ---------------------------------------------------------------- procedural characters
def character_animation(req: ZeroLineRequest, d: Path) -> Result:
    sp = spec_for(req.line_id)
    W, H, tmp, fps = sp.width, sp.height, d / "tmp", 24
    tmp.mkdir(parents=True, exist_ok=True)
    silent = frames_to_video(puppets.caveman_scene(W, H, fps, CAVEMAN_SECONDS), tmp / "anim.mp4", W, H, fps)
    vo, cues = tts_lines(list(req.texts), tmp / "vo", lang=req.lang, gap=0.2)
    starts = place_on_beats([b - a for a, b, _ in cues])
    parts = [f"[0:a]atrim={a}:{b},asetpts=PTS-STARTPTS,adelay={int(s * 1000)}|{int(s * 1000)}[p{i}]"
             for i, ((a, b, _), s) in enumerate(zip(cues, starts, strict=True))]
    n = len(parts)
    graph = ";".join(parts) + ";" + "".join(f"[p{i}]" for i in range(n)) + \
        f"amix=inputs={n}:normalize=0,apad,atrim=0:{CAVEMAN_SECONDS}[a]"
    if n == 1:
        graph = parts[0] + f";[p0]apad,atrim=0:{CAVEMAN_SECONDS}[a]"
    sh([FFMPEG, "-y", "-v", "error", "-i", str(vo), "-filter_complex", graph, "-map", "[a]", str(tmp / "vo_timed.wav")])
    audio = mix(tmp / "vo_timed.wav", write_bgm(tmp / "bgm.wav", CAVEMAN_SECONDS + 1, "warm"), tmp / "mix.wav", CAVEMAN_SECONDS)
    ev = [(s, s + (b - a) + 0.4, "Cap", t) for (a, b, t), s in zip(cues, starts, strict=True)]
    ass = _write_ass(tmp / "c.ass", W, H, ev)
    final = finish(silent, audio, d / f"{req.line_id}.mp4", ass)
    return {"finals": [final],
            "provenance": [{"source": "procedural 2D puppet (PIL) zerolines.oskill_impl.puppets.caveman_scene",
                            "licence": "own"}, PIPER_PROV, BGM_PROV],
            "notes": "actions: walk-in 0-4.5s, crouch+pick stone 4.5-7s, light/raise torch 7-10s, turn 10-11s; "
                     "lines start on the action beats"}


def _presenter_video(tmp: Path, wav: Path, W: int, H: int, fps: int = 24, seconds: float | None = None,
                     **kw: Any) -> Path:
    mouth = mouth_series(rms_envelope(wav, fps))
    if seconds:
        n = max(1, int(seconds * fps))
        mouth = list(mouth[:n]) + [0.0] * max(0, n - len(mouth))
    p = puppets.Presenter(W, H, **kw)
    return frames_to_video((np.asarray(p.frame(i, float(m), fps)) for i, m in enumerate(mouth)),
                           tmp / f"presenter_{W}x{H}.mp4", W, H, fps)


def talking_head(req: ZeroLineRequest, d: Path) -> Result:
    sp = spec_for(req.line_id)
    W, H, tmp = sp.width, sp.height, d / "tmp"
    vo, cues = tts_lines(list(req.texts), tmp / "vo", lang=req.lang)
    total = max(30.0, dur(vo) + 0.4)
    pv = _presenter_video(tmp, vo, W, H, seconds=total)
    audio = mix(vo, write_bgm(tmp / "bgm.wav", total + 1, "warm"), tmp / "mix.wav", total, -26)
    ev = caption_events(cues)
    if _title(req):
        ev.append((0.3, 4.5, "Lower", r"{\an7\pos(60,80)\fad(300,300)\fs34}" + _title(req)))
    ass = _write_ass(tmp / "t.ass", W, H, ev)
    final = finish(pv, audio, d / f"{req.line_id}.mp4", ass)
    return {"finals": [final],
            "provenance": [{"source": "procedural 2D presenter, mouth driven by VO RMS (5 visemes)", "licence": "own"},
                           PIPER_PROV, BGM_PROV],
            "notes": "2D illustrated lip-sync from audio amplitude; NOT a photoreal digital human "
                     "(photoreal host = renderer='talkcraft', Wav2Lip)"}


def avatar_spokesperson(req: ZeroLineRequest, d: Path) -> Result:
    sp = spec_for(req.line_id)
    W, H, tmp = sp.width, sp.height, d / "tmp"
    vo, cues = tts_lines(list(req.texts), tmp / "vo", lang=req.lang)
    total = max(30.0, dur(vo) + 0.8)
    used: set[int] = set()
    seg = total / len(req.queries) + 0.5
    shots, prov = [], []
    orient = _orient(W, H)
    stills_query, still_every = _stills_args(req)
    used_titles: set[str] = set()
    for i, q in enumerate(req.queries):
        if stills_query and still_every > 0 and i % still_every == 0:
            try:
                img = topic_still(stills_query, width=max(W, H), exclude=used_titles)
                prov.append({"source": img.get("source", "topic_still"), "query": stills_query,
                             "title": img.get("title", ""), "author": img.get("author", ""),
                             "licence": img.get("licence", ""), "used_for": f"shot {i + 1}"})
                shots.append(still_shot(img["path"], tmp / f"s{i}.mp4", seg, W, H,
                                        move=DEFAULT_MOVES[i % 4]))
                continue
            except Exception:
                pass
        s = pexels(q, orientation=orient, min_d=4, exclude=used)
        prov.append(_prov(s, f"shot {i + 1}"))
        shots.append(shot(s["path"], tmp / f"s{i}.mp4", seg, W, H, move=DEFAULT_MOVES[i % 4]))
    film = xfade_concat(shots, tmp / "film.mp4", 0.5)
    P = int(min(W, H) * 0.34)
    pv = _presenter_video(tmp, vo, P, P, seconds=total, bg=((235, 245, 250), (200, 225, 240)), suit=(40, 110, 90),
                          skin=(245, 210, 185), hair=(25, 20, 18), tie=(240, 190, 60), studio=False)
    comp = tmp / "comp.mp4"
    sh([FFMPEG, "-y", "-v", "error", "-i", str(film), "-i", str(pv), "-filter_complex",
        f"[1:v]format=rgba,geq=lum='p(X,Y)':a='if(lte(hypot(X-{P / 2},Y-{P / 2}),{P / 2 - 4}),255,0)'[c];"
        f"[0:v][c]overlay=W-w-50:H-h-120:shortest=1,format=yuv420p[v]", "-map", "[v]", "-c:v", "libx264",
        "-preset", "veryfast", "-crf", "20", str(comp)])
    audio = mix(vo, write_bgm(tmp / "bgm.wav", total + 1, "bright"), tmp / "mix.wav", total, -22)
    ev = [(a, b, "Cap", rf"{{\an1\pos(70,{H - 70})}}" + t) for a, b, t in cues]
    cta = str(req.extras.get("cta") or "")
    if _title(req):
        ev.append((0.3, total - (3 if cta else 0.3), "Lower", r"{\an7\pos(70,60)\fs34}" + _title(req)))
    if cta:
        ev.append((total - 3, total, "Title", r"{\fad(300,0)\fs64}" + cta))
    ass = _write_ass(tmp / "a.ass", W, H, ev)
    final = finish(comp, audio, d / f"{req.line_id}.mp4", ass)
    return {"finals": [final],
            "provenance": [*prov, {"source": "procedural 2D presenter PiP, RMS lip-sync", "licence": "own"}, PIPER_PROV, BGM_PROV],
            "notes": "spokesperson layout: stock b-roll + circular presenter PiP + lower third + CTA card"}


# ---------------------------------------------------------------- source-media family
def _source(req: ZeroLineRequest) -> Path:
    p = Path(req.media_path)
    if not p.is_file():
        raise ZeroMediaError(f"source media not found: {req.media_path}")
    return p


def _source_or_topic(req: ZeroLineRequest, tmp: Path, W: int, H: int) -> Path:
    """Uploaded source wins; otherwise derive a narrated topic source."""
    if req.media_path and Path(req.media_path).is_file():
        return Path(req.media_path)
    if req.media_path:
        raise ZeroMediaError(f"source media not found: {req.media_path}")
    src, _ = _synth_source(req, tmp, W, H, lines_n=14)
    return src


def shorts_clip(req: ZeroLineRequest, d: Path) -> Result:
    sp = spec_for(req.line_id)
    W, H, tmp = sp.width, sp.height, d / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    src = _source_or_topic(req, tmp / "src", W, H)
    lang = str(req.extras.get("source_lang") or req.lang)
    segs = whisper_segments(src, lang)
    (d / "transcript.json").write_text(json.dumps(segs, ensure_ascii=False, indent=1), encoding="utf-8")
    wins = pick_windows(segs, n=int(req.extras.get("clips") or 2), target=(27, 33))
    if not wins:
        wins = pick_windows(segs, n=int(req.extras.get("clips") or 2), target=(20, 35))
    if not wins:
        raise ZeroMediaError("no speech window found in the source")
    outs = []
    for k, (i, j) in enumerate(wins):
        a, b = max(0.0, segs[i]["start"] - 0.2), segs[j]["end"] + 0.3
        if b - a > 31:
            b = a + 30.0
        if b - a < 27:
            try:
                from hevi.layer4_legacy.zerolines.omodul_impl._media import dur as _dur

                b = min(_dur(str(src)), a + 30.0)
            except Exception:
                pass
        ev = []
        for s in segs[i:j + 1]:
            for c0, c1, text in word_chunks(s["words"], size=4):
                ev.append((c0 - a, c1 - a, "Cap",
                           rf"{{\an5\pos({W // 2},{int(H * 0.72)})\fs54\bord5\fad(60,60)}}"
                           + (text.upper() if lang == "en" else text)))
        if _title(req):
            ev.append((0, b - a, "Kicker", rf"{{\an8\pos({W // 2},140)\fs38}}" + _title(req)))
        _write_ass(tmp / f"c{k}.ass", W, H, ev)
        out = d / f"{req.line_id}_{k + 1:02d}.mp4"
        sh([FFMPEG, "-y", "-v", "error", "-ss", f"{a:.2f}", "-t", f"{b - a:.2f}", "-i", str(src), "-filter_complex",
            f"[0:v]split[bg][fg];[bg]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=30:3,"
            f"eq=brightness=-0.15[b];[fg]scale={W}:-2:flags=lanczos,unsharp=5:5:0.6[f];[b][f]overlay=0:(H-h)/2-80,"
            f"{subtitles_filter(tmp / f'c{k}.ass')}[v]",
            "-map", "[v]", "-map", "0:a", "-af", "loudnorm=I=-15", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
            "-c:a", "aac", "-metadata", "comment=run-" + __import__("time").strftime("%s.%f"), "-movflags", "+faststart", str(out)])
        outs.append(out)
    return {"finals": outs,
            "provenance": [{"source": "user-supplied source media", "path": str(src)},
                           {"source": f"faster-whisper ({Path(_wm()).name}, local CPU) word timestamps"}],
            "notes": f"{len(outs)} vertical clips from whisper-picked speech windows",
            "artifacts": {"transcript": str(d / "transcript.json")}}


def _wm() -> str:
    from hevi.layer4_legacy.zerolines.omodul_impl._media import WHISPER_MODEL

    return WHISPER_MODEL


def podcast_repurpose(req: ZeroLineRequest, d: Path) -> Result:
    sp = spec_for(req.line_id)
    W, H, tmp = sp.width, sp.height, d / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    src = _source_or_topic(req, tmp / "src", W, H)
    lang = str(req.extras.get("source_lang") or req.lang)
    segs = whisper_segments(src, lang)
    (d / "transcript.json").write_text(json.dumps(segs, ensure_ascii=False, indent=1), encoding="utf-8")
    wins = pick_windows(segs, n=1, target=(27, 33))
    if not wins:
        wins = pick_windows(segs, n=1, target=(20, 35))
    if not wins:
        raise ZeroMediaError("no 20-35 s speech window found in the source")
    (i, j), = wins
    a, b = max(0.0, segs[i]["start"] - 0.2), segs[j]["end"] + 0.3
    if b - a > 31:
        b = a + 30.0
    if b - a < 27:
        try:
            from hevi.layer4_legacy.zerolines.omodul_impl._media import dur as _dur

            b = min(_dur(str(src)), a + 30.0)
        except Exception:
            pass
    ev = [(s["start"] - a, s["end"] - a, "Cap",
           rf"{{\an5\pos({W // 2},{int(H * 0.80)})\fs40}}" + s["text"])
          for s in segs[i:j + 1]]
    show, sub = str(req.extras.get("show") or ""), str(req.extras.get("subtitle") or "")
    if show:
        ev.append((0, b - a, "Kicker", r"{\an7\pos(330,150)\fs30\c&H00C8FF&}" + show))
    if _title(req):
        ev.append((0, b - a, "Title", r"{\an7\pos(330,200)\fs52}" + _title(req)))
    if sub:
        ev.append((0, b - a, "Kicker", r"{\an7\pos(330,275)\fs26\c&HCCCCCC&}" + sub))
    ass = _write_ass(tmp / "p.ass", W, H, ev)
    out = d / f"{req.line_id}.mp4"
    sh([FFMPEG, "-y", "-v", "error", "-ss", f"{a:.2f}", "-t", f"{b - a:.2f}", "-i", str(src), "-filter_complex",
        f"color=c=0x101820:s={W}x{H}:r=30[bgc];"
        f"[0:v]scale=240:240:force_original_aspect_ratio=increase,crop=240:240[cov];"
        f"[0:a]asplit=3[a1][a2][a3];"
        f"[a1]showwaves=s={W - 160}x220:mode=cline:colors=0x00C8FF|0x0088CC:rate=30,format=rgba[w];"
        # scrolling spectrogram band: the audiogram visibly advances every frame while audio plays
        f"[a3]showspectrum=s={W - 160}x150:slide=scroll:mode=combined:color=cool:scale=log:fps=30,format=rgba[sp];"
        f"[bgc][cov]overlay=60:120[t1];[t1][w]overlay=80:440:shortest=1[t2];[t2][sp]overlay=80:670:shortest=1,"
        f"drawbox=x=60:y=ih-60:w='(iw-120)*t/{b - a:.2f}':h=8:color=0x00C8FF:t=fill,"
        f"{subtitles_filter(ass)}[v]",
        "-map", "[v]", "-map", "[a2]", "-c:v", "libx264", "-preset", "medium", "-crf", "20",         "-c:a", "aac",
        "-metadata", "comment=run-" + __import__("time").strftime("%s.%f"),
        "-movflags", "+faststart", str(out)])
    return {"finals": [out],
            "provenance": [{"source": "user-supplied source media", "path": str(src)},
                           {"source": f"faster-whisper ({Path(_wm()).name}, local CPU)"}],
            "notes": "audiogram: live source cover + waveform + scrolling spectrogram + captions + progress bar",
            "artifacts": {"transcript": str(d / "transcript.json")}}


def reference_adapt(req: ZeroLineRequest, d: Path) -> Result:
    sp = spec_for(req.line_id)
    W, H, tmp = sp.width, sp.height, d / "tmp"
    ref = _source(req)

    # Breakdown-driven mode: if breakdown card or mode is specified in extras
    if req.extras.get("mode") == "breakdown_driven" or req.extras.get("breakdown_path") or req.extras.get("breakdown"):
        from hevi.viralclone import (
            compile_viral_template,
            draft_template_from_breakdown,
            reference_breakdown,
        )
        bd_path = req.extras.get("breakdown_path")
        if bd_path and Path(bd_path).is_file():
            bd_dict = json.loads(Path(bd_path).read_text(encoding="utf-8"))
        elif isinstance(req.extras.get("breakdown"), dict):
            bd_dict = req.extras["breakdown"]
        else:
            bd_res = reference_breakdown({}, {"video_path": str(ref)}, tmp / "breakdown")
            if bd_res.get("status") != "succeeded":
                raise ZeroMediaError(f"breakdown failed: {bd_res.get('reason')}")
            bd_dict = json.loads(Path(bd_res["report"]["breakdown_json"]).read_text(encoding="utf-8"))

        template_spec = req.extras.get("template") or draft_template_from_breakdown(bd_dict).to_dict()
        slots = dict(req.extras.get("slots") or {})
        if req.texts:
            slots["hook_line"] = req.texts[0]
            for idx, txt in enumerate(req.texts[1:], start=1):
                slots[f"selling_point_{idx}"] = txt
        if req.title and "product" not in slots:
            slots["product"] = req.title

        compile_inp = {
            "template": template_spec,
            "slots": slots,
            "brolls": [str(ref), *list(req.extras.get("brolls") or [])],
            "product_video": str(req.extras.get("product_video") or ""),
            "output_name": req.line_id,
            "aspect_ratio": "9:16" if (W, H) == (720, 1280) else "16:9",
        }
        compile_res = compile_viral_template(compile_inp["template"], compile_inp["slots"], d,
                                             brolls=compile_inp["brolls"], product_video=compile_inp["product_video"],
                                             aspect_ratio=compile_inp["aspect_ratio"])
        if compile_res.get("status") != "succeeded":
            raise ZeroMediaError(f"compile_and_render_template failed: {compile_res.get('reason')}")
        final = Path(compile_res["report"]["video_path"])
        return {
            "finals": [final],
            "provenance": [
                {"source": "breakdown-driven reference media", "path": str(ref)},
                PIPER_PROV,
            ],
            "notes": "reference breakdown-driven: word-anchored template with GB 45438 AI watermark and dynamic cuts",
            "artifacts": {
                "timeline": compile_res["report"]["timeline_path"],
                "subtitles": compile_res["report"]["ass_path"],
                "breakdown": bd_path or str(tmp / "breakdown" / "breakdown.json"),
            },
        }

    ref_d = dur(ref)
    bad = [o for o in req.offsets if not 0 <= o < ref_d]
    if bad:
        raise ZeroMediaError(f"reference offsets outside the {ref_d:.1f}s reference: {bad}")
    vo, cues = tts_lines(list(req.texts), tmp / "vo", lang=req.lang)
    lengths = _fit_lengths(narration_shot_lengths(cues, xd=0.6, tail=1.0), 0.6)
    total = sum(lengths) - 0.6 * (len(lengths) - 1)
    shots = [shot(ref, tmp / f"s{k}.mp4", seg, W, H, ss=float(ss), move=("push", "pan_r", "pull", "pan_l")[k % 4],
                  grade="scale=iw:ih:flags=lanczos,unsharp=5:5:0.8,eq=contrast=1.08:saturation=1.2")
             for k, (seg, ss) in enumerate(zip(lengths, req.offsets, strict=True))]
    film = xfade_concat(shots, tmp / "film.mp4", 0.6, "circleopen")
    ev = caption_events(cues)
    if _title(req):
        ev = [(0.2, 3.0, "Title", r"{\fad(300,300)}" + _title(req)), *ev]
    ass = _write_ass(tmp / "r.ass", W, H, ev)
    audio = mix(vo, write_bgm(tmp / "bgm.wav", total + 1, "warm"), tmp / "mix.wav", total)
    final = finish(film, audio, d / f"{req.line_id}.mp4", ass)
    return {"finals": [final],
            "provenance": [{"source": "user-supplied reference media", "path": str(ref),
                            "segments_used_s": list(req.offsets)}, PIPER_PROV, BGM_PROV],
            "notes": "reference re-structured: chosen segments, new narration, grade, moves, transitions, captions"}


def documentary_montage(req: ZeroLineRequest, d: Path) -> Result:
    sp = spec_for(req.line_id)
    W, H, tmp = sp.width, sp.height, d / "tmp"
    stills_query, still_every = _stills_args(req)
    film, audio, cues, prov, _ = _broll_film(
        req, tmp, W, H,
        moves=("pull", "pan_r", "push", "pan_l", "pull", "push", "pan_r"),
        grade="eq=saturation=0.62:contrast=1.06:gamma=0.98,noise=alls=7:allf=t+u",
        mood="tense", xd=0.7,
        stills_query=stills_query or (req.topic or ""), still_every=still_every or 1,
    )
    labels = list(req.labels) or ["档案 01", "影像 02", "现场 03", "物证 04", "口述 05", "年表 06", "回望 07"]
    ev = caption_events(cues)
    for (a, b, _), lab in zip(cues, labels, strict=False):
        if lab:
            ev.append((a, b, "Lower", r"{\an7\pos(64,86)\fad(250,250)\fs40\c&H00D7FF&}" + lab))
    ev.append((0.2, cues[-1][1] if cues else 4.0, "Kicker",
               r"{\an9\pos(654,70)\fs30\c&HE0E0E0&}ARCHIVE"))
    if _title(req):
        ev.insert(0, (0.2, 3.4, "Title", r"{\fad(400,400)}" + _title(req)))
    ass = _write_ass(tmp / "dm.ass", W, H, ev)
    final = finish(film, audio, d / f"{req.line_id}.mp4", ass)
    return {"finals": [final], "provenance": [*prov, PIPER_PROV, BGM_PROV],
            "notes": "archival montage: muted grade + film grain + archive lower-thirds"}


def _synth_source(req: ZeroLineRequest, tmp: Path, W: int, H: int, *, lines_n: int = 14,
                  lang: str | None = None) -> tuple[Path, list[str]]:
    """Build a topic-derived source video (spoken narration + b-roll stills/video).

    Used when a source-media line is asked with only a topic.  The source is a
    real narrated clip, so the downstream whisper/dub/clip stages run on real
    speech instead of a placeholder.
    """
    lang = lang or req.lang
    topic = (req.topic or req.title or (req.texts[0] if req.texts else "")).strip()
    if not topic:
        raise ZeroMediaError(f"{req.line_id}: needs a media_path or a topic to derive a source")
    first = list(generate_script_lines(topic, lang=lang, line_id="explainer", n=min(7, lines_n)))
    rest = []
    if len(first) < lines_n:
        rest = list(generate_script_lines(topic, lang=lang, line_id="history_scene", n=lines_n - len(first)))
    lines = first + rest
    queries = list(generate_broll_queries(topic, tuple(lines), lang=lang, line_id="explainer"))
    sub = ZeroLineRequest(line_id="explainer", texts=tuple(lines), queries=tuple(queries),
                          topic=topic, title=req.title or topic, lang=lang)
    stills_query, still_every = _stills_args(sub)
    film, audio, _cues, _prov, _ = _broll_film(
        sub, tmp, W, H, moves=("push", "pan_r", "pull", "pan_l"),
        grade="eq=saturation=1.0:contrast=1.02", mood="warm",
        stills_query=stills_query, still_every=still_every or 2,
    )
    src = tmp / "source.mp4"
    finish(film, audio, src)
    return src, lines


def localization_dub(req: ZeroLineRequest, d: Path) -> Result:
    """Dub an uploaded (or topic-derived) source into the target language."""
    sp = spec_for(req.line_id)
    W, H, tmp = sp.width, sp.height, d / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    src_txt = Path(req.media_path) if req.media_path else None
    if src_txt is not None and not src_txt.is_file():
        raise ZeroMediaError(f"source media not found: {req.media_path}")
    if src_txt is None:
        src_txt, _lines = _synth_source(req, tmp / "src", W, H, lines_n=8)
    source_lang = str(req.extras.get("source_lang") or req.lang or "zh")
    target_lang = str(req.extras.get("target_lang") or ("en" if source_lang.startswith("zh") else "zh"))
    if target_lang not in ("zh", "en"):
        raise ZeroMediaError(f"localization_dub: unsupported target language {target_lang!r} (zh|en)")
    segs = [s for s in whisper_segments(src_txt, source_lang) if s["start"] < 29.6]
    if not segs:
        raise ZeroMediaError("localization_dub: no speech found in the source")
    dub_dir = tmp / "dub"
    dub_dir.mkdir(parents=True, exist_ok=True)
    parts, cues = [], []
    for k, seg in enumerate(segs[:14]):
        original = str(seg.get("text") or "").strip()
        if not original:
            continue
        spoken = translate_text(original, source=source_lang, target=target_lang) or original
        slot = max(1.2, min(7.0, float(seg["end"]) - float(seg["start"])))
        p = dub_dir / f"{k:02d}.wav"
        dur_s = tts(spoken, p, lang=target_lang, speed=1.0)
        if dur_s > slot * 1.02:
            dur_s = tts(spoken, p, lang=target_lang, speed=min(1.5, dur_s / slot))
        start = max(0.0, float(seg["start"]))
        parts.append((p, start, min(slot + 0.9, max(dur_s, 0.8))))
        cues.append((start, min(29.9, start + min(slot, dur_s) + 0.35), spoken, original))
    if not cues:
        raise ZeroMediaError("localization_dub: translation produced no lines")
    inputs, graph = [], []
    for i, (p, start, hold) in enumerate(parts):
        inputs += ["-i", str(p)]
        graph.append(f"[{i}:a]atrim=0:{hold:.3f},asetpts=PTS-STARTPTS,"
                     f"adelay={int(start * 1000)}|{int(start * 1000)}[a{i}]")
    n = len(parts)
    fc = ";".join(graph) + ";" + "".join(f"[a{i}]" for i in range(n)) + \
        f"amix=inputs={n}:normalize=0,apad,atrim=0:30[a]"
    dub_wav = tmp / "dub.wav"
    sh([FFMPEG, "-y", "-v", "error", *inputs, "-filter_complex", fc, "-map", "[a]", "-ar", "44100", str(dub_wav)])
    bed = tmp / "bed.wav"
    sh([FFMPEG, "-y", "-v", "error", "-i", str(src_txt), "-vn", "-af", "apad,atrim=0:30", "-ar", "44100", str(bed)])
    audio = mix(dub_wav, bed, tmp / "mix.wav", 30, -20)
    video = shot(src_txt, tmp / "video.mp4", 30.0, W, H, ss=0.0, move="push",
                 grade="eq=contrast=1.03:saturation=1.02")
    ev = []
    bilingual = bool(req.extras.get("bilingual", True))
    for a, b, spoken, original in cues:
        ev.append((a, b, "Cap", rf"{{\an5\pos({W // 2},{H - 190})\fs40\bord4}}" + spoken))
        if bilingual:
            ev.append((a, b, "Cap", rf"{{\an5\pos({W // 2},{H - 130})\fs26\c&HCCCCCC&}}" + original))
    if _title(req):
        ev.append((0.2, 4.0, "Lower", r"{\an7\pos(60,80)\fs34}" + _title(req)))
    ass = _write_ass(tmp / "d.ass", W, H, ev)
    final = finish(video, audio, d / f"{req.line_id}.mp4", ass)
    return {"finals": [final],
            "provenance": [{"source": "user-supplied source" if req.media_path else "topic-derived source",
                            "path": str(src_txt)},
                           {"source": "free translation (MyMemory) + piper local TTS"}],
            "notes": f"dub {source_lang}->{target_lang}; bilingual captions; original audio kept as low bed"}


def comic_narration(req: ZeroLineRequest, d: Path) -> Result:
    from hevi.layer4_legacy.comicnarr.omodul_impl.comicnarr_pipeline import (
        comic_narration_workflow,
    )

    sp = spec_for(req.line_id)
    topic = req.topic or (req.texts[0] if req.texts else "")
    from hevi.layer4_legacy.zerolines.omodul_impl._media import translate_to_english

    input_data = {
        "topic": topic,
        "subject_en": translate_to_english(topic) if topic else "",
        "texts": list(req.texts),
        "style": req.extras.get("style", "guofeng_anime"),
        "subtitle_style": req.extras.get("subtitle_style", "bottom"),
        "keyframe_engine": req.extras.get("keyframe_engine", "sdturbo_cpu"),
        "base_seed": int(req.extras.get("base_seed", 42)),
        "width": sp.width,
        "height": sp.height,
    }
    workflow_out = comic_narration_workflow({}, input_data, d)
    final_mp4 = Path(workflow_out["final_mp4"])
    return {
        "finals": [final_mp4],
        "provenance": [
            {"source": "SD-Turbo CPU keyframe engine (TAESD decoder)"},
            PIPER_PROV,
            BGM_PROV,
        ],
        "notes": "comic narration: sentence-by-sentence keyframes + TTS + BGM + Ken Burns + subtitles",
        "artifacts": {
            "qa": workflow_out.get("qa_path"),
            "record": workflow_out.get("record_path"),
            "script": workflow_out.get("script_path"),
            "contact_sheet": workflow_out.get("contact_sheet"),
        },
    }


PRODUCERS: dict[str, Callable[[ZeroLineRequest, Path], Result]] = {
    f.__name__: f
    for f in (kinetic_promo, explainer, cinematic, director_pipeline, history_scene, character_animation,
              talking_head, avatar_spokesperson, shorts_clip, podcast_repurpose, reference_adapt, comic_narration,
              documentary_montage, localization_dub)
}
