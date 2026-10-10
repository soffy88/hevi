"""SHOTBOOK planner (oskill layer: pure + deterministic, no I/O).

Turns narration segments + aligned sentence timings into a workbench
``ProjectData`` timeline for the ``hevi-remotion-talkcraft`` Main composition.

Methodology internalized from talkcraft's SKILL.md / references:
- one semantic beat per narrated sentence; the card's entrance is anchored to
  the aligned time of its key word (word-level sync), not to the sentence start;
- a card is never repeated back-to-back and the role decides the card family
  (title / list / term / emphasis / quote / number / CTA);
- text is budgeted per card (no over-long single lines); long sentences fall
  back to line-based cards;
- a continuously moving backdrop sits under transparent-root cards and a
  three-colour wipe marks every segment change, so no beat is a still slide.
Same input -> byte-identical plan (sorted, no randomness, no clock).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from typing import Any

from hevi.layer4_legacy.talkcraft.oprim_impl.sync import (
    FPS,
    STAGE_H,
    STAGE_W,
    Beat,
    NarrationSegment,
    SentenceTiming,
    TalkcraftPlan,
    norm_chars,
)

ACCENT = "#e8720c"
MAX_LEAD_S = 0.8
SUBTITLE_CLASH = frozenset({"keyword-pop-highlight"})
PUSH = 0.06  # +6% scale across a beat
DRIFT_PX = 14.0  # stage px (x2 at delivery)
INK = "#1d1d1f"

_CLAUSE = re.compile(r"[，,。！？!?；;：:、]")
_END_PUNCT = "。！？!?.；;，,"


def clauses(text: str) -> list[str]:
    return [c.strip() for c in _CLAUSE.split(text) if c.strip()]


def wrap_lines(text: str, *, width: int = 12, max_lines: int = 4) -> list[str]:
    """Split on clauses, then hard-wrap clauses longer than ``width``."""
    out: list[str] = []
    for c in clauses(text) or [text.strip()]:
        while len(c) > width:
            out.append(c[:width])
            c = c[width:]
        if c:
            out.append(c)
    if len(out) > max_lines:
        head = out[: max_lines - 1]
        tail = "".join(out[max_lines - 1 :])
        out = head + [tail[: width - 1] + "…" if len(tail) > width else tail]
    return out


def pick_keyword(text: str, keywords: Sequence[str]) -> str:
    """The word the beat lands on: a storyboard keyword if spoken, else a short clause tail."""
    for kw in keywords:
        if kw and norm_chars(kw) and norm_chars(kw) in norm_chars(text) and kw in text:
            return kw
    cs = [c for c in clauses(text) if 2 <= len(c) <= 6]
    if cs:
        return min(cs, key=lambda c: (len(c), text.find(c)))
    core = text.rstrip(_END_PUNCT)
    return core[-3:] if len(core) >= 3 else core


def _split_around(text: str, kw: str) -> tuple[str, str, str]:
    core = text.rstrip(_END_PUNCT)
    i = core.find(kw)
    if i < 0:
        return core, "", ""
    return core[:i], kw, core[i + len(kw) :]


def focus_clause(text: str, kw: str, n: int = 12) -> str:
    """The clause carrying the key word (single-line cards never truncate mid-thought)."""
    cs = clauses(text) or [text]
    hit = next((c for c in cs if kw and kw in c), cs[0])
    return _short(hit, n)


def _short(text: str, n: int) -> str:
    t = text.rstrip(_END_PUNCT)
    return t if len(t) <= n else t[: n - 1] + "…"


# --------------------------------------------------------------------------
# Card library: id -> (lead prop name | None, transparent-root?, builder)
# Builders receive (sentence text, keyword, segment props) and return props.
# --------------------------------------------------------------------------
Builder = Callable[[str, str, dict[str, Any]], dict[str, Any]]


def _two_lines(text: str, kw: str, _p: dict[str, Any]) -> dict[str, Any]:
    ls = wrap_lines(text, width=10, max_lines=2)
    return {"line1": ls[0], "line2": ls[1] if len(ls) > 1 else kw}


CARDS: dict[str, tuple[str | None, bool, Builder]] = {
    "slab-punch-title": ("lead", True, _two_lines),
    "speed-slab-title": (
        "lead",
        True,
        lambda t, kw, p: {"line1": _short(_split_around(t, kw)[0] or t, 10), "slabText": _short(kw, 6)},
    ),
    "tracking-in": ("lead", True, lambda t, kw, p: {"text": focus_clause(t, kw), "textColor": INK}),
    "per-character-rise": ("lead", True, lambda t, kw, p: {"text": focus_clause(t, kw)}),
    "soft-blur-in": ("lead", True, lambda t, kw, p: {"text": focus_clause(t, kw), "textColor": INK}),
    "split-text-stagger": (
        None,
        True,
        lambda t, kw, p: {"text": _short(kw, 8), "sub": _short(t, 22)},
    ),
    "keyword-pop-highlight": (
        "delay",
        True,
        lambda t, kw, p: dict(
            zip(("textBefore", "keyword", "textAfter"), _split_around(_short(t, 16), kw), strict=True)
        ),
    ),
    "ink-underline": (
        "startDelay",
        True,
        lambda t, kw, p: {
            "line1Pre": _split_around(_short(t, 14), kw)[0],
            "line1Key": kw,
            "line1Post": _split_around(_short(t, 14), kw)[2],
            "line2Pre": "",
            "line2Key": "",
            "line2Post": "",
            "fontSize": 40,
        },
    ),
    "hand-drawn-ellipse": (
        "startDelay",
        True,
        lambda t, kw, p: {"leadText": _short(_split_around(t, kw)[0] or t, 12), "ringWord": _short(kw, 6)},
    ),
    "converging-arrows": (
        "startDelay",
        True,
        lambda t, kw, p: {
            "leadText": "",
            "preText": _split_around(_short(t, 14), kw)[0],
            "focusText": kw,
            "postText": _split_around(_short(t, 14), kw)[2],
            "fontSize": 38,
            "focusSize": 52,
        },
    ),
    "line-by-line-slide": (
        "lead",
        True,
        lambda t, kw, p: {"lines": "\n".join(wrap_lines(t, width=12, max_lines=4))},
    ),
    "quote-card": (
        "lead",
        True,
        lambda t, kw, p: {
            "lines": "\n".join(
                ln.replace(kw, f"**{kw}**", 1) if kw and kw in ln else ln
                for ln in wrap_lines(t, width=10, max_lines=4)
            ),
            "source": "",
        },
    ),
    "corner-bracket-frame": ("lead", True, _two_lines),
    "numbered-step-stack": (
        "lead",
        True,
        lambda t, kw, p: {"stepsDsl": "\n".join(_short(x, 12) for x in p["_items"][:4])},
    ),
    "step-timeline-vertical": (
        "lead",
        True,
        lambda t, kw, p: {
            "stepsDsl": "\n".join(
                f"{i + 1:02d}|{_short(x, 12)}" for i, x in enumerate(p["_items"][:4])
            )
        },
    ),
    "title-demote-to-label": (
        None,
        True,
        lambda t, kw, p: {
            "title": _short(p.get("_title") or kw, 12),
            "items": "\n".join(_short(x, 14) for x in p["_items"][:4]),
        },
    ),
    "info-term-card": (
        None,
        True,
        lambda t, kw, p: {
            "term": _short(p.get("_term") or kw, 8),
            "termSmall": "",
            "desc": _short(p.get("_desc") or t, 30),
            "iconChar": (p.get("_term") or kw or "?")[:1],
        },
    ),
    "chapter-title-card": (
        "startAt",
        False,
        lambda t, kw, p: {"num": p.get("_num", "01"), "name": _short(p.get("_title") or t, 12), "sub": ""},
    ),
}

# Role -> preference order for "free" sentences (no structured props needed).
EMPHASIS_ROTATION: tuple[str, ...] = (
    "keyword-pop-highlight",
    "ink-underline",
    "tracking-in",
    "soft-blur-in",
    "converging-arrows",
    "split-text-stagger",
    "per-character-rise",
    "corner-bracket-frame",
)
LONG_ROTATION: tuple[str, ...] = ("line-by-line-slide", "quote-card")


def _items_for(seg: NarrationSegment) -> tuple[str | None, list[str]]:
    """Structured list content from the storyboard props, if the scene has one."""
    p = seg.props or {}
    if seg.role == "hook":
        return p.get("title"), [i.get("label", "") for i in p.get("items", []) if i.get("label")]
    if seg.role == "cards":
        return p.get("header"), [c.get("title", "") for c in p.get("cards", []) if c.get("title")]
    if seg.role == "method":
        return p.get("header"), [pt.get("title", "") for pt in p.get("points", []) if pt.get("title")]
    if seg.role == "definition":
        return p.get("formulaHead") or p.get("formula_head"), list(
            p.get("formulaLines") or p.get("formula_lines") or []
        )
    return None, []


def _structured_choice(seg: NarrationSegment, k: int) -> tuple[str, dict[str, Any]] | None:
    """Card for sentence ``k`` of a segment when its props carry structure."""
    p = seg.props or {}
    title, items = _items_for(seg)
    if k == 0 and seg.role == "hook" and title:
        return "slab-punch-title", {"_override": {"line1": _short(title, 10), "line2": _short(p.get("subtitle", ""), 12) or ""}}
    if k == 1 and len(items) >= 2 and seg.role in ("hook", "cards"):
        return "title-demote-to-label", {"_title": title, "_items": items}
    if k == 0 and len(items) >= 2 and seg.role == "method":
        return "step-timeline-vertical", {"_items": items}
    if k == 0 and len(items) >= 2 and seg.role == "definition":
        return "numbered-step-stack", {"_items": items}
    if k == 0 and seg.role == "cards" and items:
        cards = p.get("cards") or []
        return "info-term-card", {"_term": cards[0].get("title"), "_desc": cards[0].get("desc")}
    if seg.role == "reason" and k == 0 and p.get("bubbleText"):
        return "quote-card", {"_override_text": p["bubbleText"]}
    if seg.role == "outro" and k == 0 and (p.get("quoteLine1") or p.get("quote_line1")):
        q = (p.get("quoteLine1") or p.get("quote_line1") or "") + "，" + (p.get("quoteLine2") or p.get("quote_line2") or "")
        return "quote-card", {"_override_text": q}
    return None


def _anchored_lead(
    *, timing: SentenceTiming, kw: str, beat_s: float, default: float = 0.3
) -> tuple[float, float | None]:
    """Card entrance offset (s, beat-local) so the motion lands on the key word."""
    t = timing.char_time(substring=kw)
    if t is None:
        return default, None
    offset = t - timing.start_s
    lead = max(0.1, offset - 0.25)
    # cap: a card may wait for its word, but never leave the stage empty for long
    lead = min(lead, MAX_LEAD_S, max(0.1, beat_s - 1.4))
    return round(lead, 2), round(offset, 3)


def plan_project(
    *,
    name: str,
    segments: Sequence[NarrationSegment],
    timings: Sequence[SentenceTiming],
    voice_file: str,
    total_s: float,
    tail_s: float = 0.6,
) -> TalkcraftPlan:
    """Deterministic SHOTBOOK -> workbench ProjectData."""
    flat = [(seg, k, s) for seg in segments for k, s in enumerate(seg.sentences)]
    if len(flat) != len(timings):
        raise ValueError(f"{len(flat)} sentences but {len(timings)} timings")

    beats: list[Beat] = []
    card_clips: list[dict[str, Any]] = []
    sub_clips: list[dict[str, Any]] = []
    fx_clips: list[dict[str, Any]] = []
    prev_card = ""
    used: dict[str, int] = {}
    rot = 0
    end_frame_total = int(round((total_s + tail_s) * FPS))

    for n, ((seg, k, text), tm) in enumerate(zip(flat, timings, strict=True)):
        start_f = int(round(tm.start_s * FPS))
        nxt = timings[n + 1].start_s if n + 1 < len(timings) else total_s + tail_s
        dur_f = max(15, int(round(nxt * FPS)) - start_f)
        beat_s = dur_f / FPS
        kw = pick_keyword(text, seg.keywords)

        choice = _structured_choice(seg, k)
        if choice and choice[0] == prev_card:
            choice = None
        if choice:
            card_id, extra = choice
        else:
            extra = {}
            pool = LONG_ROTATION if len(text.rstrip(_END_PUNCT)) > 16 else EMPHASIS_ROTATION
            # least-used card in the pool, rotation order breaks ties; never repeat back-to-back
            ordered = [pool[(rot + i) % len(pool)] for i in range(len(pool))]
            ordered = [c for c in ordered if c != prev_card] or ordered
            card_id = min(ordered, key=lambda c: (used.get(c, 0), ordered.index(c)))
            rot += 1

        lead_key, alpha, build = CARDS[card_id]
        merged = {**(seg.props or {}), **extra}
        src_text = extra.get("_override_text") or text
        props = dict(extra["_override"]) if "_override" in extra else build(src_text, kw, merged)
        lead, anchor = _anchored_lead(timing=tm, kw=kw, beat_s=beat_s)
        if lead_key:
            props[lead_key] = lead
        if alpha:
            props["__alpha"] = True
        # one slow camera curve per shot (anti-slideshow): alternate push/drift direction
        props["__push"] = PUSH if n % 2 == 0 else PUSH * 0.8
        props["__driftX"] = DRIFT_PX if n % 2 == 0 else -DRIFT_PX

        used[card_id] = used.get(card_id, 0) + 1
        prev_card = card_id
        clip_id = f"{seg.id}-s{k:02d}"
        card_clips.append(_clip(clip_id, card_id, start_f, dur_f, props, label=f"{seg.id}#{k}"))
        if card_id not in SUBTITLE_CLASH:  # these cards already set the sentence low on stage
            sub_clips.append(
                _clip(f"{clip_id}-sub", "koubo-subtitle-line", start_f, dur_f, {"text": text.rstrip(_END_PUNCT)})
            )
        if k == 0 and n > 0:  # segment boundary -> three-colour wipe centred on the cut
            fx_clips.append(_clip(f"{seg.id}-wipe", "koubo-wipe", max(0, start_f - 10), 21, {}))
        beats.append(
            Beat(
                segment_id=seg.id,
                sentence_index=k,
                role=seg.role,
                card_id=card_id,
                start_frame=start_f,
                duration_frames=dur_f,
                anchor_word=kw,
                anchor_offset_s=anchor,
                props={kk: vv for kk, vv in props.items() if not kk.startswith("__")},
            )
        )

    project = {
        "name": name,
        "fps": FPS,
        "width": STAGE_W,
        "height": STAGE_H,
        "tracks": [  # tracks[0] is the TOP layer
            {"id": "fx", "name": "转场", "clips": fx_clips},
            {"id": "subs", "name": "字幕", "clips": sub_clips},
            {"id": "cards", "name": "动效卡", "clips": card_clips},
            {
                "id": "bg",
                "name": "幕底",
                "clips": [_clip("bg", "bg-mesh", 0, end_frame_total, {})],
            },
            {
                "id": "voice",
                "name": "配音",
                "clips": [_clip("vo", "audio-clip", 0, end_frame_total, {"file": voice_file, "volume": 1})],
            },
        ],
    }
    return TalkcraftPlan(project=project, beats=beats)


def _clip(cid: str, card: str, start: int, dur: int, props: dict[str, Any], label: str | None = None) -> dict[str, Any]:
    c: dict[str, Any] = {
        "id": cid,
        "cardId": card,
        "start": int(start),
        "duration": int(dur),
        "inOffset": 0,
        "speed": 1,
        "opacity": 1,
        "scale": 1,
        "x": 0,
        "y": 0,
        "props": props,
    }
    if label:
        c["label"] = label
    return c
