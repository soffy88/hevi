"""Stable-film assembly pipeline (``pipeline.stable_film_assembly``).

Clean-room method rewrite for the B1-B7 baseline in the stable-film
deep-dive report (section 4): a commentary review film that can be
delivered without any paid motion channel and without scene pictures.

Nothing here duplicates an existing gate. It only wires them, in
order, into one assembly and refuses to call the result finished
when a gate fails or material is missing:

* ``video.segment_assembly_gate`` -- sentence shots packed into
  segments capped at the smaller of 15 seconds and the model limit.
* ``story.asset_registry_v2`` -- pending shots never enter the
  generation list; the pending list travels with the film.
* ``edit.subtitle_discipline`` -- captions re-broken after the cut
  (a long breath unit becomes two timed events at a recorded
  phrase boundary, characters unchanged), glossary
  canonicalised, and the vertical safe zone measured from a real
  extracted frame (see ``measure_caption_bbox``), never estimated
  from a margin value.
* ``video.motion_beat_chart`` -- gated on motion beats only.
  Placeholder beats (pending material) are drawn as static cards,
  labelled as pending on the card and in the footnote, and are NOT
  counted toward the 0.80 real-change ratio.
* ``audio.mix_recipe`` -- voice-only films are normalised to the
  recipe targets (-14 +/- 2 LUFS, true peak at most -1 dB) with the
  same two-pass loudnorm measurement the recipe uses; films with
  BGM go through ``mix_recipe.run_mix`` itself, so the ducking
  wiring (voice-keyed sidechain compressor, fixed recipe values)
  is the recipe's, not a copy.
* ``qa.final_qc_gate`` -- run on the assembled film, including its
  whole-film picture-change rate (floor 0.30), always with the
  defect scan enabled (fail-closed: a scan that did not run is
  a failed gate, see ``gate_all``), and with the Otsu
  rendered-text measurement over the caption bar (CJK text is
  reported undetermined -- its error is uncalibrated).
* ``qa.timeline_gate`` -- run before rendering on a timeline
  derived from the segments and subtitle events (or on a
  caller-supplied timeline): scene gaps, hook legibility and
  caption speed are caught while they are still cheap.
* ``qa.critic_review`` -- a caller-supplied review record is
  judged in the main path; only a ``ship`` verdict passes, and
  no record at all is a missing gate, never a pass. The record
  is supplied by the caller: this pipeline never invents a
  reviewer, and the review discipline stays a record judgment,
  not a fresh-subagent review.

Two confirmation points (B6) are strict. A confirmation only counts
when it is a dict with ``confirmed`` exactly ``True`` and the right
``stage``. Pre-synthesis confirmation unlocks synthesis only;
post-gate confirmation unlocks release of that one package only,
and only when every failed / missing / undetermined gate is named
in ``acknowledged``. "Continue" never approves a whole-film batch:
there is no batch approval in this module at all.

Delivery status (B7) is derived, never asserted by the caller:

* ``finished`` -- every gate passes, no pending material, no
  missing segments. Only then may the file be called a finished
  film.
* ``partial`` -- a segment is missing or material is pending
  (gate failures, if any, are still listed alongside).
* ``review`` -- gates fail or are missing/undetermined, with no
  missing segment or pending material.
* ``refused`` -- pre-synthesis confirmation missing or invalid;
  nothing is rendered.
* ``failed`` -- the film could not even be assembled (for example
  ffmpeg is absent); no output file is claimed.

Missing segments are never padded with blank frames, repeated
frames or older output: a missing segment is listed, and the film
is partial. Placeholder cards are not finished scenes and are
never counted as motion.
"""

from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from hevi.capabilities import asset_registry as _asset_registry
from hevi.capabilities import critic_review as _critic_review
from hevi.capabilities import final_qc as _final_qc
from hevi.capabilities import mix_recipe as _mix_recipe
from hevi.capabilities import motion_beat_chart as _motion_beat
from hevi.capabilities import segment_assembly as _segment_assembly
from hevi.capabilities import subtitle_discipline as _subtitle
from hevi.capabilities import timeline_gate as _timeline_gate
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

BEAT_MIN_REAL_RATIO = 0.80
PICTURE_MIN_CHANGE_RATE = 0.30
TARGET_LUFS = -14.0
LUFS_TOLERANCE = 2.0
TRUE_PEAK_CEILING_DB = -1.0
VERTICAL_SAFE_BOTTOM = 0.80
MAX_SUBTITLE_CHARS = 15
SEGMENT_CAP_SEC = 15.0
_SENTENCE_RE = re.compile(r"[^。？！；]+[。？！；]?")
_LOUDNORM_RE = re.compile(r"\{[^}]*\"input_i\"[^}]*\}")
_FONT_CANDIDATES = [
    "/home/soffy/.local/share/fonts/wqy-zenhei.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc",
]
_REAL_KINDS = [
    "move", "grow", "gather", "draw_path", "zoom", "morph",
    "light_up", "flow", "reveal", "scatter", "spin", "bounce",
]


# ---------------------------------------------------------------- confirmations

def check_confirmation(confirmation: Any, stage: str) -> dict[str, Any]:
    """Strict confirmation check: ``confirmed`` must be exactly True.

    Anything else -- False, "yes", 1, a missing stage, a missing
    dict -- is a refusal that names the reason. Silence, skipping
    and timeout are not confirmations because they never arrive
    here as ``confirmed is True``.
    """
    if not isinstance(confirmation, dict):
        return {"allowed": False, "stage": stage,
                "reason": "no confirmation supplied (expected a dict)"}
    if confirmation.get("stage") != stage:
        return {"allowed": False, "stage": stage,
                "reason": (
                    f"confirmation stage is {confirmation.get('stage')!r}, "
                    f"not {stage!r}; a confirmation for one stage never "
                    "unlocks another stage"
                )}
    if confirmation.get("confirmed") is not True:
        return {"allowed": False, "stage": stage,
                "reason": "confirmed is not exactly True; synthesis/release is refused"}
    return {"allowed": True, "stage": stage, "reason": ""}


def build_line_capacity(segments: list[dict[str, Any]]) -> dict[str, Any]:
    """Line-capacity ledger for the pre-synthesis confirmation point.

    Totals plus a per-segment row (characters, seconds, chars per
    second). A segment longer than the 15-second cap is flagged
    here as well as by the segment gate; flagging is not fixing.
    """
    rows = []
    total_chars = 0
    total_sec = 0.0
    for seg in segments:
        text = str(seg.get("text", "") or "")
        dur = float(seg.get("duration_sec") or 0.0)
        chars = len(text)
        total_chars += chars
        total_sec += dur
        rows.append({
            "segment_id": seg.get("segment_id", ""),
            "chars": chars,
            "duration_sec": round(dur, 3),
            "chars_per_sec": round(chars / dur, 2) if dur > 0 else None,
            "over_cap": dur > SEGMENT_CAP_SEC,
        })
    return {
        "segments": rows,
        "total_chars": total_chars,
        "total_sec": round(total_sec, 3),
        "overall_chars_per_sec": (
            round(total_chars / total_sec, 2) if total_sec > 0 else None
        ),
    }


def check_pre_synthesis(storyboard_rows: Any, capacity: Any,
                        confirmation: Any) -> dict[str, Any]:
    """Pre-synthesis confirmation point (B6, first point).

    Refuses synthesis when the confirmation is not strict-True for
    stage ``pre_synthesis``, when the storyboard is empty, or when
    the capacity ledger is missing. A refusal names every reason.
    """
    conf = check_confirmation(confirmation, "pre_synthesis")
    reasons = []
    if not conf["allowed"]:
        reasons.append(conf["reason"])
    if not isinstance(storyboard_rows, list) or not storyboard_rows:
        reasons.append("storyboard is empty; nothing to confirm")
    if not isinstance(capacity, dict) or "total_chars" not in capacity:
        reasons.append("line-capacity ledger is missing")
    return {"allowed": not reasons, "reasons": reasons,
            "confirmation": conf}


# ---------------------------------------------------------------- subtitles

# Characters after which a re-break prefers to fall: phrase
# particles, conjunctions and locative endings. A re-break is a
# timed-event boundary, not a line break, so it must still land
# somewhere; preferring these boundaries keeps it off the middle
# of a word group whenever one is near the balanced point.
_BOUNDARY_ENDINGS = set("的 地 得 着 了 过 在 对 向 跟 和 与 或 但 而 就 才 都 也 还 是 上 下 里 中 前 后 内 外")


def _balanced_chunks(unit: str, budget: int = MAX_SUBTITLE_CHARS) -> list[str]:
    """Split one over-budget breath unit into balanced chunks.

    No character is deleted, added or reordered; joining the
    chunks returns the unit exactly. The first chunk size is the
    size nearest the balanced target (unit length / chunk count)
    that ends after a boundary character when one is within four
    characters of the target; ties go to the earlier break. The
    split points are recorded by the caller so a human can see
    where the re-break fell.
    """
    if len(unit) <= budget:
        return [unit]
    n = math.ceil(len(unit) / budget)
    target = len(unit) / n
    lo = max(1, int(target) - 4)
    hi = min(budget, len(unit) - (n - 1), int(target) + 4)
    candidates = list(range(lo, hi + 1))
    boundary = [s for s in candidates if unit[s - 1] in _BOUNDARY_ENDINGS]
    pool = boundary if boundary else candidates
    size = min(pool, key=lambda s: (abs(s - target), s))
    return [unit[:size]] + _balanced_chunks(unit[size:], budget)


def split_sentences(text: str) -> list[str]:
    """Split narration text into sentences (same rule as the test gates)."""
    return [p for p in _SENTENCE_RE.findall(str(text or "")) if p.strip()]


def build_sentence_shots(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sentence shots for the segment gate, durations pro-rata.

    A sentence that still runs over 15 seconds is kept as-is so
    the segment gate can fail and name it; this function never
    trims a shot to fit.
    """
    shots = []
    for seg in segments:
        sentences = split_sentences(seg.get("text", ""))
        total_chars = sum(len(s) for s in sentences) or 1
        dur = float(seg.get("duration_sec") or 0.0)
        for j, sentence in enumerate(sentences):
            shots.append({
                "shot_id": f"{seg.get('segment_id', 'seg')}-{j + 1}",
                "text": sentence,
                "duration_sec": round(dur * len(sentence) / total_chars, 3),
            })
    return shots


def build_subtitle_events(segments: list[dict[str, Any]],
                          glossary: dict[str, list[str]] | None = None
                          ) -> dict[str, Any]:
    """Re-break captions after the cut (B4).

    Each sentence is broken into breath units; any unit longer
    than the 15-character vertical budget becomes two or more
    timed events (balanced chunks, no deletion) instead of one
    forced mid-phrase line. Every event text is then run through
    the discipline re-flow (glossary canonicalisation + line
    packing), so the returned events are already canonical.
    """
    glossary = glossary or {}
    events: list[dict[str, Any]] = []
    resplits: list[dict[str, Any]] = []
    for seg in segments:
        seg_id = seg.get("segment_id", "")
        start_base = float(seg.get("start_sec") or 0.0)
        sentences = split_sentences(seg.get("text", ""))
        total_chars = sum(len(s) for s in sentences) or 1
        cursor = start_base
        for sentence in sentences:
            sent_dur = float(seg.get("duration_sec") or 0.0) * len(sentence) / total_chars
            units: list[str] = []
            for unit in _subtitle.split_breath_units(sentence):
                if len(unit) > MAX_SUBTITLE_CHARS:
                    chunks = _balanced_chunks(unit)
                    resplits.append({"segment_id": seg_id, "original_unit": unit,
                                     "chunks": chunks,
                                     "note": "re-broken into timed events; no characters deleted"})
                    units.extend(chunks)
                else:
                    units.append(unit)
            unit_chars = sum(len(u) for u in units) or 1
            for unit in units:
                unit_dur = sent_dur * len(unit) / unit_chars
                flow = _subtitle.reflow_event_text(unit, glossary)
                events.append({
                    "start_sec": round(cursor, 3),
                    "end_sec": round(cursor + unit_dur, 3),
                    "text": flow["glossaried"],
                    "lines": flow["lines"],
                    "glossary_replaced": flow["glossary_replaced"],
                    "segment_id": seg_id,
                })
                cursor += unit_dur
    return {"events": events, "resplits": resplits,
            "event_count": len(events)}


def format_srt(events: list[dict[str, Any]]) -> str:
    """Render subtitle events as SRT text (lines already re-broken)."""
    def _stamp(sec: float) -> str:
        sec = max(0.0, float(sec))
        ms = int(round((sec - int(sec)) * 1000))
        return f"{int(sec) // 3600:02d}:{(int(sec) % 3600) // 60:02d}:{int(sec) % 60:02d},{ms:03d}"
    blocks = []
    for i, ev in enumerate(events, 1):
        lines = ev.get("lines") or [ev.get("text", "")]
        blocks.append(f"{i}\n{_stamp(ev['start_sec'])} --> {_stamp(ev['end_sec'])}\n" + "\n".join(lines))
    return "\n\n".join(blocks) + ("\n" if blocks else "")


# ---------------------------------------------------------------- safe-zone frame measure

def measure_caption_bbox(frame_path: Path) -> dict[str, Any]:
    """Measure a caption block's bottom edge from a real frame (B4).

    Method (written into the result, not hidden): convert the
    frame to greyscale, mark pixels whose horizontal or vertical
    neighbour differs by more than 50 levels as edge pixels, and
    look only at the bottom 45% of the frame. Rows with at least
    max(30, 3% of width) edge pixels are text rows; text rows
    grouped with gaps of at most 3% of frame height, and at least
    4 rows tall, form a caption cluster. The cluster's last row
    divided by frame height is the measured bottom fraction.

    When no cluster is found the result is ``measured: False``
    with status ``undetermined`` -- never a guessed pass. A
    margin-derived estimate is not accepted here: callers must
    pass an extracted frame, not a number.
    """
    method = (
        "greyscale edge rows in bottom 45% of frame; row threshold "
        "max(30, 3% of width); clusters bridged over gaps up to 3% "
        "of height, min 4 rows tall; bottom = last cluster row / height"
    )
    try:
        import numpy as np
    except ImportError:
        return {"measured": False, "status": "undetermined",
                "bottom_fraction": None, "method": method,
                "reason": "numpy is not available for frame measurement"}
    path = Path(frame_path)
    if not path.is_file():
        return {"measured": False, "status": "undetermined",
                "bottom_fraction": None, "method": method,
                "reason": f"frame file not found: {path}"}
    img = Image.open(path).convert("L")
    width, height = img.size
    arr = np.asarray(img, dtype=float)
    edge = np.zeros_like(arr, dtype=bool)
    edge[:, :-1] |= np.abs(arr[:, 1:] - arr[:, :-1]) > 50
    edge[:-1, :] |= np.abs(arr[1:, :] - arr[:-1, :]) > 50
    row_score = edge.sum(axis=1)
    start_row = int(height * 0.55)
    threshold = max(30, int(0.03 * width))
    gap_allow = max(4, int(0.03 * height))
    qualifying = [y for y in range(start_row, height) if row_score[y] >= threshold]
    if not qualifying:
        return {"measured": False, "status": "undetermined",
                "bottom_fraction": None, "method": method,
                "reason": "no caption edge cluster found in bottom 45% of frame"}
    groups: list[list[int]] = [[qualifying[0]]]
    for y in qualifying[1:]:
        if y - groups[-1][-1] <= gap_allow:
            groups[-1].append(y)
        else:
            groups.append([y])
    groups = [g for g in groups if len(g) >= 4]
    if not groups:
        return {"measured": False, "status": "undetermined",
                "bottom_fraction": None, "method": method,
                "reason": "edge rows found but no cluster at least 4 rows tall"}
    best = max(groups, key=lambda g: float(row_score[g].sum()))
    bottom = (best[-1] + 1) / height
    return {"measured": True, "status": "measured",
            "bottom_fraction": round(bottom, 3),
            "top_fraction": round(best[0] / height, 3),
            "method": method, "frame": str(path),
            "safe_zone_pass": bottom <= VERTICAL_SAFE_BOTTOM}


# ---------------------------------------------------------------- assets and beats

def check_assets(registry: Any, episode_id: str,
                 shot_ids: list[str]) -> dict[str, Any]:
    """Asset check (B5): pending shots never enter generation.

    Returns the registry's pending list verbatim plus the derived
    generation list (all shots minus pending shots). An unknown
    episode or a missing registry is a missing gate, named as such,
    not a pass.
    """
    if registry is None:
        return {"ready": False, "pending_material": [],
                "pending_shot_ids": [], "generation_shot_ids": list(shot_ids),
                "missing": "no asset registry supplied for episode "
                           f"{episode_id!r}"}
    try:
        report = _asset_registry.check_episode(registry, episode_id)
    except CapabilityError as exc:
        return {"ready": False, "pending_material": [],
                "pending_shot_ids": [], "generation_shot_ids": list(shot_ids),
                "missing": str(exc)}
    pending = report.get("pending_material") or []
    pending_ids = sorted({str(p.get("shot_id", "")) for p in pending if p.get("shot_id")})
    return {"ready": bool(report.get("ready")),
            "pending_material": pending,
            "pending_shot_ids": pending_ids,
            "generation_shot_ids": [s for s in shot_ids if s not in pending_ids],
            "missing": None}


def build_beats(segments: list[dict[str, Any]],
                pending_segment_ids: set[str],
                thesis: dict[str, Any] | None = None) -> dict[str, Any]:
    """One beat per segment; pending segments become static cards.

    Motion beats get a real change kind (cycled through the
    renderer's kinds, so the kind on the chart is the kind drawn).
    Pending beats get ``static`` and are kept out of the motion
    gate's denominator by ``gate_all`` -- they are placeholders,
    not motion.
    """
    beats, motion_beats, placeholder_beats = [], [], []
    for i, seg in enumerate(segments):
        seg_id = seg.get("segment_id", "")
        kind = "static" if seg_id in pending_segment_ids else _REAL_KINDS[i % len(_REAL_KINDS)]
        beat = {
            "start_sec": float(seg.get("start_sec") or 0.0),
            "end_sec": float(seg.get("start_sec") or 0.0) + float(seg.get("duration_sec") or 0.0),
            "action": ("placeholder card: pending material, not a scene"
                       if kind == "static" else f"code-motion {kind}"),
            "mover": "placeholder card" if kind == "static" else "code-motion disc and stars",
            "state_change": ("card stays still; material pending"
                             if kind == "static" else f"state changes by {kind} across the beat"),
            "camera": "locked" if kind == "static" else "locked (motion is in-scene)",
            "text": str(seg.get("title", "") or seg_id),
            "asset": str(seg.get("asset_id", "") or ""),
            "change_kind": kind,
            "segment_id": seg_id,
            "placeholder": kind == "static",
        }
        beats.append(beat)
        (placeholder_beats if kind == "static" else motion_beats).append(beat)
    chart_thesis = thesis or {
        "visual_metaphor": "light gathers as the explanation builds",
        "from_state": "question on screen",
        "to_state": "answer on screen",
        "claim": "the explanation, not a picture, carries the film",
    }
    return {"thesis": chart_thesis, "beats": beats,
            "motion_beats": motion_beats, "placeholder_beats": placeholder_beats}


# ---------------------------------------------------------------- code-motion frames

@lru_cache(maxsize=None)
def _load_font(size: int) -> Any:
    for cand in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(cand, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _wrap(text: str, width: int) -> list[str]:
    out, cur = [], ""
    for ch in str(text or ""):
        if len(cur) >= width:
            out.append(cur)
            cur = ""
        cur += ch
    if cur:
        out.append(cur)
    return out or [""]


def _draw_motion(draw: ImageDraw.ImageDraw, width: int, height: int,
                 kind: str, progress: float) -> None:
    """Draw one frame's moving content for a beat kind.

    Every kind changes real pixels as ``progress`` moves 0 -> 1,
    so a one-second-apart frame pair differs well above the
    final-QC change threshold. No kind here is a fade or slide.
    """
    cx, cy = width // 2, int(height * 0.35)
    gold = (240, 200, 90)
    if kind == "move":
        x = int(width * (0.15 + 0.70 * progress))
        draw.ellipse([x - 60, cy - 60, x + 60, cy + 60], fill=gold)
    elif kind == "grow":
        r = int(20 + 90 * progress)
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=gold)
    elif kind == "gather":
        for k in range(6):
            ang = math.pi * 2 * k / 6
            dist = 200 * (1 - progress) + 20
            x, y = cx + int(dist * math.cos(ang)), cy + int(dist * math.sin(ang))
            draw.ellipse([x - 22, y - 22, x + 22, y + 22], fill=gold)
    elif kind == "draw_path":
        pts = []
        n = max(2, int(2 + 40 * progress))
        for i in range(n):
            x = int(width * 0.15 + (width * 0.70) * i / 40)
            y = cy + int(60 * math.sin(i / 40 * math.pi * 2))
            pts.append((x, y))
        draw.line(pts, fill=gold, width=8)
        if pts:
            x, y = pts[-1]
            draw.ellipse([x - 18, y - 18, x + 18, y + 18], fill=(255, 255, 255))
    elif kind == "zoom":
        for ring in range(1, 5):
            r = int(ring * 40 * (0.6 + progress))
            draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=gold, width=5)
    elif kind == "morph":
        rx = int(30 + 130 * progress)
        ry = int(110 - 70 * progress)
        draw.ellipse([cx - rx, cy - ry, cx + rx, cy + ry], fill=gold)
    elif kind == "light_up":
        count = max(1, int(math.ceil(progress * 12)))
        for k in range(12):
            if k >= count:
                continue
            x = int(width * (0.12 + 0.76 * ((k * 37) % 12) / 11))
            y = int(height * (0.10 + 0.30 * ((k * 53) % 7) / 6))
            draw.ellipse([x - 10, y - 10, x + 10, y + 10], fill=(255, 255, 220))
    elif kind == "flow":
        pts = []
        for i in range(41):
            x = int(width * 0.10 + (width * 0.80) * i / 40)
            y = cy + int(60 * math.sin(i / 40 * math.pi * 2 + progress * math.pi * 2))
            pts.append((x, y))
        draw.line(pts, fill=gold, width=10)
    elif kind == "reveal":
        w = int(width * progress)
        draw.rectangle([0, int(height * 0.12), w, int(height * 0.58)], fill=(70, 110, 180))
    elif kind == "scatter":
        for k in range(8):
            ang = math.pi * 2 * k / 8
            dist = int(30 + 200 * progress)
            x, y = cx + int(dist * math.cos(ang)), cy + int(dist * math.sin(ang))
            draw.ellipse([x - 18, y - 18, x + 18, y + 18], fill=gold)
    elif kind == "spin":
        ang = progress * math.pi * 2
        x2, y2 = cx + int(140 * math.cos(ang)), cy + int(140 * math.sin(ang))
        draw.line([(cx, cy), (x2, y2)], fill=gold, width=12)
        draw.ellipse([x2 - 20, y2 - 20, x2 + 20, y2 + 20], fill=(255, 255, 255))
    elif kind == "bounce":
        y = int(height * 0.55 - abs(math.sin(progress * math.pi * 2)) * height * 0.22)
        draw.ellipse([cx - 55, y - 55, cx + 55, y + 55], fill=gold)
    else:  # unknown kind: draw nothing moving; the chart gate rejects it first
        pass


def _render_frame(t: float, width: int, height: int,
                  beats: list[dict[str, Any]],
                  events: list[dict[str, Any]],
                  total_sec: float, status_note: str) -> Image.Image:
    """One deterministic frame: motion (or placeholder) + captions."""
    img = Image.new("RGB", (width, height), (18, 32, 64))
    draw = ImageDraw.Draw(img)
    beat = None
    for b in beats:
        if b["start_sec"] <= t < b["end_sec"] or (
                b is beats[-1] and t >= b["start_sec"]):
            beat = b
            break
    if beat is None and beats:
        beat = beats[-1]
    title_font = _load_font(max(12, int(30 * width / 540)))
    body_font = _load_font(max(11, int(24 * width / 540)))
    sub_font = _load_font(max(11, int(26 * width / 540)))
    foot_font = _load_font(max(10, int(18 * width / 540)))
    if beat is not None:
        if beat.get("placeholder"):
            draw.rectangle([width // 10, height // 8, width * 9 // 10, height * 5 // 8],
                           fill=(30, 30, 40), outline=(240, 200, 90), width=3)
            draw.text((width // 10 + 16, height // 8 + 16), "待素材",
                      fill=(240, 200, 90), font=title_font)
            y = height // 8 + 16 + int(44 * width / 540)
            for line in _wrap(beat.get("text", ""), max(8, width // 34)):
                draw.text((width // 10 + 16, y), line, fill=(235, 235, 235), font=body_font)
                y += int(32 * width / 540)
            draw.text((width // 10 + 16, y + 8), "本卡不是场景图",
                      fill=(150, 160, 175), font=foot_font)
        else:
            span = max(1e-6, beat["end_sec"] - beat["start_sec"])
            progress = min(1.0, max(0.0, (t - beat["start_sec"]) / span))
            _draw_motion(draw, width, height, str(beat.get("change_kind", "")), progress)
            y = int(height * 0.06)
            for line in _wrap(beat.get("text", ""), max(8, width // 30)):
                draw.text((24, y), line, fill=(240, 240, 240), font=title_font)
                y += int(40 * width / 540)
    active = None
    for ev in events:
        if ev["start_sec"] <= t < ev["end_sec"]:
            active = ev
            break
    if active is not None:
        lines = active.get("lines") or [active.get("text", "")]
        bar_top = int(height * 0.68)
        draw.rectangle([0, bar_top, width, int(height * 0.79)], fill=(0, 0, 0))
        y = bar_top + 8
        for line in lines[:2]:
            draw.text((16, y), line, fill=(255, 255, 255), font=sub_font)
            y += int(34 * width / 540)
    draw.text((16, int(height * 0.82)), status_note, fill=(150, 160, 175), font=foot_font)
    return img


def _require_tool(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        raise CapabilityError(f"pipeline.stable_film_assembly: required tool missing: {name}")
    return path


def _pad_tail_if_needed(mp4_path: Path) -> dict[str, Any]:
    """Clone-pad the tail when the video stream ends before the audio.

    A ``-shortest`` mux can drop the last video frame, leaving the
    video stream a fraction of a frame shorter than the container.
    Final QC takes its last frame from the container duration, so
    that gap makes its last-frame extraction fail even though the
    film itself is fine. When the video stream is shorter than
    the container, this clones the last frame and pads audio with
    silence to 0.2 s past the container duration, so a frame
    always covers the QC last stamp. The added tail is silence
    plus a still frame, never a substitute for a missing segment,
    and the 0.2 s stays inside the QC duration tolerance.
    Returns a note dict (``padded`` True/False, durations).
    """
    try:
        ffprobe = _require_tool("ffprobe")
        proc = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries",
             "stream=codec_type,duration", "-show_entries", "format=duration",
             "-of", "json", str(mp4_path)],
            capture_output=True, text=True, timeout=120)
        data = json.loads(proc.stdout)
        video_dur = None
        for stream in data.get("streams") or []:
            if stream.get("codec_type") == "video":
                video_dur = float(stream.get("duration"))
                break
        format_dur = float((data.get("format") or {}).get("duration"))
    except Exception:
        return {"padded": False, "reason": "durations unprobeable; left unchanged"}
    if video_dur is None or video_dur >= format_dur:
        return {"padded": False, "video_duration": video_dur,
                "format_duration": format_dur}
    extra = (format_dur - video_dur) + 0.2
    total = format_dur + 0.2
    tmp = mp4_path.with_suffix(".padded.mp4")
    proc = subprocess.run(
        [_require_tool("ffmpeg"), "-y", "-v", "error", "-i", str(mp4_path),
         "-vf", f"tpad=stop_mode=clone:stop_duration={extra:.3f}",
         "-af", "apad", "-t", f"{total:.3f}",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
         "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", str(tmp)],
        capture_output=True, text=True, timeout=600)
    if proc.returncode != 0 or not tmp.is_file():
        tmp.unlink(missing_ok=True)
        return {"padded": False, "reason": f"tail pad failed: {proc.stderr.strip()[-200:]}"}
    shutil.move(str(tmp), str(mp4_path))
    return {"padded": True, "video_duration": video_dur,
            "format_duration": format_dur, "added_sec": round(extra, 3)}


def _extract_frame(video_path: Path, at_sec: float, out_path: Path) -> None:
    ffmpeg = _require_tool("ffmpeg")
    proc = subprocess.run(
        [ffmpeg, "-y", "-v", "error", "-ss", f"{at_sec:.3f}",
         "-i", str(video_path), "-frames:v", "1", str(out_path)],
        capture_output=True, text=True, timeout=120)
    if proc.returncode != 0 or not out_path.is_file():
        raise CapabilityError(
            f"pipeline.stable_film_assembly: frame extraction failed: {proc.stderr.strip()}")


# ---------------------------------------------------------------- audio (recipe targets)

def normalize_voice_audio(voice_path: Path, out_path: Path) -> dict[str, Any]:
    """Voice-only normalisation to the mix-recipe targets.

    Two-pass loudnorm: measure first, then apply with the measured
    values and linear=true. The apply pass aims 0.5 dB below the
    recipe's true-peak ceiling because the later AAC encode can
    lift the true peak by about a tenth of a dB; the final
    verification is still against the recipe ceiling itself
    (-1 dB). Films with BGM do not use this function at all
    (they use run_mix).
    """
    ffmpeg = _require_tool("ffmpeg")
    voice_path, out_path = Path(voice_path), Path(out_path)
    if not voice_path.is_file():
        raise CapabilityError(f"pipeline.stable_film_assembly: voice file not found: {voice_path}")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [ffmpeg, "-i", str(voice_path), "-af",
         f"loudnorm=I={TARGET_LUFS}:TP={TRUE_PEAK_CEILING_DB}:LRA=11:print_format=json",
         "-f", "null", "-"],
        capture_output=True, text=True, timeout=600)
    match = _LOUDNORM_RE.search(proc.stderr or "")
    if not match:
        raise CapabilityError("pipeline.stable_film_assembly: loudnorm measurement not found")
    try:
        measured = json.loads(match.group(0))
        vals = {k: float(measured[k]) for k in
                ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")}
    except (KeyError, TypeError, ValueError) as exc:
        raise CapabilityError(
            "pipeline.stable_film_assembly: loudnorm measurement incomplete") from exc
    if not all(math.isfinite(v) for v in vals.values()):
        raise CapabilityError("pipeline.stable_film_assembly: loudnorm measurement not finite")
    apply_tp = TRUE_PEAK_CEILING_DB - 0.5  # AAC headroom; verified against -1 dB later
    filt = (
        f"loudnorm=I={TARGET_LUFS}:TP={apply_tp}:LRA=11:"
        f"measured_I={vals['input_i']}:measured_TP={vals['input_tp']}:"
        f"measured_LRA={vals['input_lra']}:measured_thresh={vals['input_thresh']}:"
        f"offset={vals['target_offset']}:linear=true"
    )
    proc = subprocess.run(
        [ffmpeg, "-y", "-v", "error", "-i", str(voice_path),
         "-af", filt, "-c:a", "pcm_s16le", str(out_path)],
        capture_output=True, text=True, timeout=600)
    if proc.returncode != 0 or not out_path.is_file():
        raise CapabilityError(
            f"pipeline.stable_film_assembly: loudnorm apply failed: {proc.stderr.strip()}")
    return {"output": str(out_path), "measured_first_pass": vals,
            "target_lufs": TARGET_LUFS, "true_peak_ceiling_db": TRUE_PEAK_CEILING_DB}


def build_timeline_for_film(
    segments: list[dict[str, Any]],
    *,
    width: int,
    height: int,
    fps: int,
    total_sec: float,
    subtitle_events: list[dict[str, Any]] | None = None,
    clock: str = "voice",
    bpm: float | None = None,
) -> dict[str, Any]:
    """Derive a ``qa.timeline_gate`` timeline from the film plan.

    Scenes are the segments (contiguous by construction; a
    caller-supplied ``start_sec`` gap is exactly what the gate
    is there to catch). The hook is the first segment's title
    or first text, starting at 0. Beats and cuts are the
    segment boundaries. Captions come from the subtitle events.
    No px sizes are declared (the renderer's title size is not
    a plan fact -- rendered size is the Otsu measurement's job),
    no terms/VO/silence are claimed: the gate warns about those
    instead of the plan inventing them. Clock defaults to
    ``voice``; ``music`` is used only when a bpm is supplied,
    because a music clock without a bpm is a gate error.
    """
    first = segments[0] if segments else {}
    hook_text = str(first.get("title") or first.get("text") or "")
    scenes = [{
        "start": float(s.get("start_sec") or 0.0),
        "end": float(s.get("start_sec") or 0.0) + float(s.get("duration_sec") or 0.0),
    } for s in segments]
    boundaries = [s["start"] for s in scenes[1:]]
    captions = [{
        "start": float(e["start_sec"]),
        "end": float(e["end_sec"]),
        "text": str(e.get("text", "")),
    } for e in (subtitle_events or [])]
    last_start = scenes[-1]["start"] if scenes else 0.0
    return {
        "meta": {
            "w": width, "h": height, "fps": fps, "dur": total_sec,
            "clock": "music" if bpm is not None else clock,
            "bpm": bpm,
        },
        "scenes": scenes,
        "beats": [s["start"] for s in scenes],
        "cuts": boundaries,
        "texts": [{
            "role": "hook",
            "text": hook_text,
            "start": 0.0,
            "end": min(3.0, max(total_sec, 0.1)),
        }] if hook_text else [],
        "captions": captions,
        "hero": {"t": last_start},
    }


# ---------------------------------------------------------------- gate combination

def delivery_filename(base: str, status: str) -> str:
    """File naming rule (B7): only a finished film may be called one.

    ``review`` files are review versions, ``partial`` files are
    partial deliveries, and no failed assembly is ever given a
    finished-film name.
    """
    stem = Path(base).stem or "film"
    if status == "finished":
        return f"{stem}_成片.mp4"
    if status == "partial":
        return f"{stem}_部分完成.mp4"
    return f"{stem}_可审版.mp4"


def footnote_text(status: str, pending: list[dict[str, Any]],
                  missing_segments: list[str], failures: list[str]) -> str:
    """Footnote / delivery-note text that travels with the film."""
    bits = []
    if status == "partial":
        bits.append("部分完成")
    elif status == "review":
        bits.append("可审版")
    elif status == "finished":
        bits.append("成片")
    if pending:
        shots = sorted({str(p.get("shot_id", "")) for p in pending if p.get("shot_id")})
        bits.append(f"待素材: {', '.join(shots)} (待素材镜未进生成, 本卡不是场景图)")
    if missing_segments:
        bits.append(f"缺段: {', '.join(missing_segments)} (缺段未用空白帧/重复帧/旧输出顶替)")
    if failures:
        bits.append(f"未通过门: {'; '.join(failures)}")
    return " | ".join(bits) if bits else "全部通过"


def gate_all(*, segment_plan: dict[str, Any] | None,
             segment_plan_error: str | None,
             motion_gate: dict[str, Any] | None,
             subtitle_gate: dict[str, Any] | None,
             safe_zone: dict[str, Any] | None,
             loudness: dict[str, Any] | None,
             final_qc_report: dict[str, Any] | None,
             asset_check: dict[str, Any] | None,
             missing_segments: list[str],
             timeline_gate_report: dict[str, Any] | None = None,
             critic_review_report: dict[str, Any] | None = None) -> dict[str, Any]:
    """Combine every gate into one verdict (B1).

    A gate that was not run, or whose result is missing, is listed
    in ``missing_gates`` and counts as a failure for finished
    status -- exactly like a failed gate, but named as missing so
    nobody mistakes it for a pass. An undetermined safe zone is
    listed separately and is likewise never a pass.

    The defect scan is fail-closed here: when the final-QC
    report carries no defect-scan summary, or a ``skipped``
    summary, the defect-scan entry fails (or is missing) even
    when every other final-QC check passed -- a film whose
    defect scan never ran is not a finished film. The critic
    entry works the same way: no review record supplied means
    ``missing``, and only a ``ship`` verdict passes.
    """
    gates: list[dict[str, Any]] = []

    def _add(name: str, verdict: str, detail: str) -> None:
        gates.append({"gate": name, "verdict": verdict, "detail": detail})

    if segment_plan_error:
        _add("video.segment_assembly_gate", "fail",
             f"segment plan failed: {segment_plan_error}")
    elif segment_plan is None:
        _add("video.segment_assembly_gate", "missing",
             "segment plan result missing: gate was not run")
    else:
        _add("video.segment_assembly_gate", "pass",
             f"{segment_plan.get('segment_count')} segments, "
             f"{segment_plan.get('total_sec')}s, cap {segment_plan.get('cap_sec')}s")
    if asset_check is None:
        _add("story.asset_registry_v2", "missing", "asset check result missing")
    elif asset_check.get("missing"):
        _add("story.asset_registry_v2", "missing", str(asset_check["missing"]))
    elif asset_check.get("pending_material"):
        shots = asset_check.get("pending_shot_ids") or []
        _add("story.asset_registry_v2", "pending",
             f"pending material for shots: {', '.join(shots)}")
    else:
        _add("story.asset_registry_v2", "pass", "episode ready, no pending material")
    if motion_gate is None:
        _add("video.motion_beat_chart", "missing", "motion gate result missing")
    elif motion_gate.get("verdict") == "pass":
        _add("video.motion_beat_chart", "pass",
             f"real-change ratio {motion_gate.get('real_change_ratio')} "
             f"(floor {BEAT_MIN_REAL_RATIO}) over motion beats only")
    else:
        _add("video.motion_beat_chart", "fail",
             f"motion gate failed: {motion_gate.get('problems')}")
    if subtitle_gate is None:
        _add("edit.subtitle_discipline", "missing", "subtitle gate result missing")
    elif subtitle_gate.get("verdict") == "pass":
        _add("edit.subtitle_discipline", "pass",
             f"{subtitle_gate.get('event_count')} events, no forced splits")
    else:
        _add("edit.subtitle_discipline", "fail",
             f"subtitle failures: {subtitle_gate.get('failures')}")
    if safe_zone is None:
        _add("vertical_caption_safe_zone_measured", "missing",
             "safe-zone frame measurement result missing")
    elif not safe_zone.get("measured"):
        _add("vertical_caption_safe_zone_measured", "undetermined",
             f"safe zone undetermined: {safe_zone.get('reason')}")
    elif safe_zone.get("safe_zone_pass"):
        _add("vertical_caption_safe_zone_measured", "pass",
             f"caption bottom measured at {safe_zone.get('bottom_fraction')} "
             f"(limit {VERTICAL_SAFE_BOTTOM}) from a real frame")
    else:
        _add("vertical_caption_safe_zone_measured", "fail",
             f"caption bottom measured at {safe_zone.get('bottom_fraction')}, "
             f"over limit {VERTICAL_SAFE_BOTTOM}")
    if loudness is None:
        _add("audio.mix_recipe", "missing", "loudness verification result missing")
    elif loudness.get("verdict") == "pass":
        _add("audio.mix_recipe", "pass", str(loudness.get("detail", "")))
    elif loudness.get("verdict") == "unmeasured":
        _add("audio.mix_recipe", "missing",
             f"loudness unmeasured: {loudness.get('detail', '')}")
    else:
        _add("audio.mix_recipe", "fail", str(loudness.get("detail", "")))
    if final_qc_report is None:
        _add("qa.final_qc_gate", "missing", "final-QC result missing")
    elif final_qc_report.get("verdict") == "pass":
        _add("qa.final_qc_gate", "pass", "all final-QC checks passed")
    else:
        failed_details = []
        for name in final_qc_report.get("failed_checks") or []:
            check = (final_qc_report.get("checks") or {}).get(name) or {}
            failed_details.append(f"{name}: {check.get('detail', '')}")
        _add("qa.final_qc_gate", "fail",
             f"failed checks: {final_qc_report.get('failed_checks')}; "
             f"skipped: {final_qc_report.get('skipped_checks')}; "
             + "; ".join(failed_details))
    # Defect scan, fail-closed: a missing or skipped scan is a
    # gate failure, not a pass, even when final QC itself passed.
    if final_qc_report is not None:
        summary = final_qc_report.get("defect_scan")
        if summary is None:
            _add("qa.final_qc_gate.defect_scan", "missing",
                 "final-QC ran without the defect scan (defect_scan was not enabled)")
        elif summary.get("status") == "skipped":
            _add("qa.final_qc_gate.defect_scan", "fail",
                 f"defect scan was skipped: {summary.get('reason')}; "
                 "a film whose defect scan did not run is not finished")
        elif summary.get("status") == "fail":
            _add("qa.final_qc_gate.defect_scan", "fail",
                 f"defect scan failed: flash={summary.get('flash')}; "
                 f"missing_cuts={summary.get('missing_cuts')}; "
                 f"unplanned_cuts={summary.get('unplanned_cuts')}")
        else:
            _add("qa.final_qc_gate.defect_scan", "pass",
                 f"defect scan ran with status {summary.get('status')!r} "
                 f"({summary.get('sample_count')} samples)")
    # Pre-render timeline gate: a failure is a gate failure; no
    # report at all is missing.
    if timeline_gate_report is None:
        _add("qa.timeline_gate", "missing", "timeline gate result missing")
    elif timeline_gate_report.get("verdict") == "fail":
        _add("qa.timeline_gate", "fail",
             "timeline errors: " + "; ".join(timeline_gate_report.get("errors") or []))
    else:
        _add("qa.timeline_gate", "pass",
             f"timeline gate passed with "
             f"{timeline_gate_report.get('warning_count', 0)} warning(s)")
    # Critic review: only a ship verdict passes. No record means
    # missing (the film was never independently reviewed); one
    # more pass, or a broken fix-round limit, means fail.
    if critic_review_report is None:
        _add("qa.critic_review", "missing",
             "no critic review record supplied: the film was never reviewed")
    elif critic_review_report.get("verdict") == "ship":
        _add("qa.critic_review", "pass",
             f"critic review ships: {critic_review_report.get('reason', '')}")
    else:
        _add("qa.critic_review", "fail",
             f"critic review verdict {critic_review_report.get('verdict')!r}: "
             f"{critic_review_report.get('reason', '')}")
    if missing_segments:
        _add("delivery.missing_segments", "pending",
             f"missing segments: {', '.join(missing_segments)}")

    failed = [g["gate"] for g in gates if g["verdict"] == "fail"]
    missing = [g["gate"] for g in gates if g["verdict"] == "missing"]
    undetermined = [g["gate"] for g in gates if g["verdict"] == "undetermined"]
    pending_gates = [g["gate"] for g in gates if g["verdict"] == "pending"]
    picture_rate = None
    if final_qc_report:
        for check in (final_qc_report.get("checks") or {}).values():
            detail = str(check.get("detail", ""))
            if "rate" in detail and "floor" in detail:
                try:
                    picture_rate = float(detail.split("rate")[1].split(",")[0].strip())
                except (IndexError, ValueError):
                    picture_rate = None
    if missing_segments or any(g["verdict"] == "pending" for g in gates):
        status = "partial"
    elif failed or missing or undetermined:
        status = "review"
    else:
        status = "finished"
    failures = [f"{g['gate']}: {g['detail']}" for g in gates if g["verdict"] in ("fail", "missing", "undetermined")]
    return {"gates": gates, "failed_gates": failed, "missing_gates": missing,
            "undetermined_gates": undetermined, "pending_gates": pending_gates,
            "status": status, "failures": failures,
            "picture_change_rate": picture_rate}


def confirm_post_gate(report: dict[str, Any], confirmation: Any,
                      acknowledged: list[str] | None = None) -> dict[str, Any]:
    """Post-gate confirmation point (B6, second point).

    Release is refused unless the confirmation is strict-True for
    stage ``post_gate`` and every failed / missing / undetermined
    gate is named in ``acknowledged``. A released package keeps
    its own status: a review package is released as a review
    package, never upgraded to finished by confirmation.
    """
    conf = check_confirmation(confirmation, "post_gate")
    if not conf["allowed"]:
        return {"released": False, "reason": conf["reason"]}
    gates = report.get("gates") or []
    open_items = [g["gate"] for g in gates
                  if g["verdict"] in ("fail", "missing", "undetermined")]
    ack = set(acknowledged or [])
    unacked = [g for g in open_items if g not in ack]
    if unacked:
        return {"released": False,
                "reason": f"gate failures not acknowledged: {', '.join(unacked)}; "
                          "fail items are not releasable unacknowledged"}
    status = report.get("status", "review")
    return {"released": True, "release_status": status,
            "released_as": ("成片" if status == "finished"
                            else "部分完成" if status == "partial" else "可审版"),
            "acknowledged": sorted(ack)}


# ---------------------------------------------------------------- full assembly

def assemble_film(*, title: str, segments: list[dict[str, Any]],
                  voice_path: Path, out_dir: Path,
                  pre_confirmation: Any,
                  registry: Any = None, episode_id: str = "episode1",
                  bgm_path: Path | None = None,
                  glossary: dict[str, list[str]] | None = None,
                  transcript_source: str = "script",
                  missing_segments: list[str] | None = None,
                  fps: int = 10, width: int = 540, height: int = 960,
                  base_name: str = "film",
                  timeline: dict[str, Any] | None = None,
                  critic_review: dict[str, Any] | None = None,
                  bpm: float | None = None,
                  rendered_text_boxes: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Assemble one film through every gate, in order (B1).

    ``segments`` carry ``segment_id``, ``text``, ``duration_sec``
    and optional ``title``, ``asset_id`` and ``start_sec`` (start
    times are computed in order when omitted). ``missing_segments``
    lists segment ids with no material at all: they are reported,
    never rendered as blank / repeated / old frames, and the film
    is partial. Pending registry shots are rendered as labelled
    placeholder cards (they are the review stand-in for a scene
    that has not been generated, not a finished scene).

    ``timeline`` (when supplied) replaces the timeline derived
    from the segments for the pre-render timeline gate.
    ``critic_review`` (when supplied) is the review record the
    critic gate judges; with none supplied the critic gate is
    missing and the film cannot finish. ``bpm`` selects the
    music clock for the derived timeline. ``rendered_text_boxes``
    (when supplied) replaces the default caption-bar Otsu
    measurement in final QC.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    missing_segments = list(missing_segments or [])
    segs: list[dict[str, Any]] = []
    cursor = 0.0
    for seg in segments:
        item = dict(seg)
        item["start_sec"] = float(seg.get("start_sec", cursor))
        item["duration_sec"] = float(seg.get("duration_sec") or 0.0)
        item.setdefault("title", seg.get("title") or seg.get("segment_id", ""))
        segs.append(item)
        cursor = item["start_sec"] + item["duration_sec"]
    total_sec = cursor

    # 1. Segment plan (sentence shots, capped) -- failure is a gate
    #    entry, not a crash, so the review package still carries it.
    shots = build_sentence_shots(segs)
    try:
        plan = _segment_assembly.plan_segments([{"scene_id": "main", "shots": shots}])
        plan_error = None
        try:
            storyboard = _segment_assembly.to_storyboard_rows(plan)
        except Exception:
            storyboard = [{"shot_id": s["shot_id"], "text": s["text"]} for s in shots]
    except CapabilityError as exc:
        plan, plan_error, storyboard = None, str(exc), []
    capacity = build_line_capacity(segs)

    # 2. Pre-synthesis confirmation point: refusal stops everything.
    pre = check_pre_synthesis(storyboard, capacity, pre_confirmation)
    if not pre["allowed"]:
        return {"capability": "pipeline.stable_film_assembly", "status": "refused",
                "reasons": pre["reasons"], "mp4": None, "gates": [],
                "failures": pre["reasons"], "missing_segments": missing_segments}

    # 3. Asset check + beats + subtitles (all before any rendering
    #    decision that could hide them).
    asset_check = check_assets(registry, episode_id, [s["shot_id"] for s in shots])
    pending_seg_ids = set()
    for p in asset_check.get("pending_material") or []:
        shot = str(p.get("shot_id", ""))
        # Pending is recorded per shot; a segment is a placeholder
        # when any of its shots is pending.
        for seg in segs:
            if shot.startswith(str(seg.get("segment_id", ""))):
                pending_seg_ids.add(str(seg.get("segment_id", "")))
    beats_info = build_beats(segs, pending_seg_ids)
    sub = build_subtitle_events(segs, glossary)
    events = sub["events"]
    # The subtitle gate is validated AFTER the safe zone is measured
    # from a real frame (step 5 below), so its safe-zone verdict and
    # the measured safe-zone entry always agree. Validating it here
    # with no bottom fraction would force a spurious
    # vertical_safe_zone_unknown failure on every vertical film.
    subtitle_gate = None
    motion_gate = None
    try:
        motion_gate = _motion_beat.gate_chart(
            {"thesis": beats_info["thesis"], "beats": beats_info["motion_beats"]})
    except CapabilityError as exc:
        motion_gate = {"capability": "video.motion_beat_chart", "verdict": "fail",
                       "problems": [{"kind": "gate_error", "detail": str(exc)}],
                       "real_change_ratio": 0.0, "beat_count": 0}

    # 3b. Pre-render timeline gate + critic record judgment, both
    #     in the main path. A failing timeline does not stop the
    #     render (the review package still carries it), but it
    #     blocks finished status in gate_all. The critic record
    #     is judged as supplied: an invalid record is a failed
    #     gate entry, never a crash, and no record at all stays
    #     None (missing gate) -- the pipeline never invents one.
    timeline_record = timeline or build_timeline_for_film(
        segs, width=width, height=height, fps=fps, total_sec=total_sec,
        subtitle_events=events, bpm=bpm)
    try:
        timeline_gate_report = _timeline_gate.check_timeline(timeline_record)
    except CapabilityError as exc:
        timeline_gate_report = {"capability": "qa.timeline_gate", "verdict": "fail",
                                "errors": [str(exc)], "warnings": [],
                                "error_count": 1, "warning_count": 0}
    critic_review_report: dict[str, Any] | None = None
    if critic_review is not None:
        try:
            critic_review_report = _critic_review.record_critic_review(critic_review)
        except CapabilityError as exc:
            critic_review_report = {"capability": "qa.critic_review",
                                    "verdict": "fail",
                                    "reason": f"invalid review record: {exc}"}

    # 4. Render (silent video, then audio) -- only possible when the
    #    tools exist; a missing tool is a failed assembly, not a film.
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        return {"capability": "pipeline.stable_film_assembly", "status": "failed",
                "reasons": ["ffmpeg/ffprobe not on PATH; nothing was rendered"],
                "mp4": None, "gates": [], "failures": ["ffmpeg/ffprobe missing"],
                "missing_segments": missing_segments}
    work = out_dir / "work"
    work.mkdir(parents=True, exist_ok=True)
    frames_dir = work / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    frame_count = max(1, round(total_sec * fps))
    status_note = "可审版"
    for i in range(frame_count):
        t = i / fps
        frame = _render_frame(t, width, height, beats_info["beats"], events,
                              total_sec, status_note)
        frame.save(frames_dir / f"frame_{i:06d}.png")
    silent = work / "silent.mp4"
    proc = subprocess.run(
        [_require_tool("ffmpeg"), "-y", "-v", "error", "-framerate", str(fps),
         "-i", str(frames_dir / "frame_%06d.png"), "-c:v", "libx264",
         "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", str(silent)],
        capture_output=True, text=True, timeout=1200)
    if proc.returncode != 0 or not silent.is_file():
        return {"capability": "pipeline.stable_film_assembly", "status": "failed",
                "reasons": [f"silent video render failed: {proc.stderr.strip()[-300:]}"],
                "mp4": None, "gates": [], "failures": ["video render failed"],
                "missing_segments": missing_segments}
    work_mp4 = work / "review_work.mp4"
    ducking = None
    if bgm_path is not None:
        mix = _mix_recipe.run_mix(Path(voice_path), Path(bgm_path), silent, work_mp4)
        ducking = mix["recipe"]["ducking"]
    else:
        norm = normalize_voice_audio(Path(voice_path), work / "voice_norm.wav")
        proc = subprocess.run(
            [_require_tool("ffmpeg"), "-y", "-v", "error", "-i", str(silent),
             "-i", str(norm["output"]), "-map", "0:v", "-map", "1:a",
             "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", str(work_mp4)],
            capture_output=True, text=True, timeout=600)
        if proc.returncode != 0 or not work_mp4.is_file():
            return {"capability": "pipeline.stable_film_assembly", "status": "failed",
                    "reasons": [f"audio mux failed: {proc.stderr.strip()[-300:]}"],
                    "mp4": None, "gates": [], "failures": ["audio mux failed"],
                    "missing_segments": missing_segments}

    # 5. Tail pad (only when the video stream ends before the
    #    container), then measured gates on the assembled film.
    tail_pad = _pad_tail_if_needed(work_mp4)
    safe_zone = None
    if events:
        mid = events[0]["start_sec"] + (events[0]["end_sec"] - events[0]["start_sec"]) / 2
        try:
            probe_frame = work / "subtitle_probe.png"
            _extract_frame(work_mp4, min(mid, max(0.0, total_sec - 0.1)), probe_frame)
            safe_zone = measure_caption_bbox(probe_frame)
        except CapabilityError as exc:
            safe_zone = {"measured": False, "status": "undetermined",
                         "bottom_fraction": None, "reason": str(exc), "method": "frame extraction"}
    srt_text = format_srt(events)
    try:
        subtitle_gate = _subtitle.validate_events(
            [{"start_sec": e["start_sec"], "end_sec": e["end_sec"], "text": e["text"]}
             for e in events],
            duration_sec=total_sec, transcript_source=transcript_source,
            glossary=glossary or {}, orientation="vertical" if height > width else "horizontal",
            subtitle_bottom_fraction=(safe_zone.get("bottom_fraction")
                                      if safe_zone and safe_zone.get("measured") else None))
    except CapabilityError as exc:
        subtitle_gate = {"capability": "edit.subtitle_discipline", "verdict": "fail",
                         "failures": [{"kind": "gate_error", "detail": str(exc)}],
                         "event_count": len(events)}
    try:
        # Otsu rendered-text measurement over the caption bar
        # (the black bar at 68-79% of frame height, where this
        # renderer draws captions). Role "caption" has no size
        # floor, so the measurement is informational; CJK text
        # is reported undetermined by final QC (uncalibrated).
        # Callers may replace the measurement with
        # rendered_text_boxes (box/at_sec/role/text entries).
        if rendered_text_boxes is not None:
            rendered_texts = rendered_text_boxes
        elif events:
            first = events[0]
            mid = first["start_sec"] + (first["end_sec"] - first["start_sec"]) / 2
            rendered_texts = [{
                "box": [0, int(height * 0.68), width, int(height * 0.79)],
                "role": "caption",
                "at_sec": mid,
                "text": first.get("text", ""),
            }]
        else:
            rendered_texts = None
        qc_report = _final_qc.run_final_qc(
            work_mp4, expected_duration_sec=total_sec, expected_codec="h264",
            subtitle_text=srt_text,
            subtitle_bottom_fraction=(safe_zone.get("bottom_fraction")
                                      if safe_zone and safe_zone.get("measured") else None),
            min_change_rate=PICTURE_MIN_CHANGE_RATE, work_dir=work / "qc",
            # Defect scan is always on in the main path (explicit
            # fail-closed: gate_all fails the film when the scan
            # did not run). planned_cuts is deliberately NOT
            # supplied: segment boundaries are motion-kind
            # changes, not luminance cuts, and passing them as
            # planned cuts makes the scan report a false
            # "missing cut" (verified 2026-10-31 on this
            # renderer). Cut-vs-plan comparison stays available
            # to callers who supply real planned cuts.
            defect_scan=True, planned_cuts=None,
            rendered_texts=rendered_texts)
    except CapabilityError as exc:
        qc_report = None
        qc_error = str(exc)
    else:
        qc_error = None
    loudness = _mix_recipe.verify_loudness(work_mp4)
    if qc_error:
        qc_report = {"capability": "qa.final_qc_gate", "verdict": "fail",
                     "failed_checks": ["gate_error"], "skipped_checks": [],
                     "checks": {"gate_error": {"pass": False, "detail": qc_error}}}

    combined = gate_all(segment_plan=plan, segment_plan_error=plan_error,
                        motion_gate=motion_gate, subtitle_gate=subtitle_gate,
                        safe_zone=safe_zone, loudness=loudness,
                        final_qc_report=qc_report, asset_check=asset_check,
                        missing_segments=missing_segments,
                        timeline_gate_report=timeline_gate_report,
                        critic_review_report=critic_review_report)
    status = combined["status"]
    delivery = out_dir / delivery_filename(base_name, status)
    shutil.copyfile(work_mp4, delivery)
    note = footnote_text(status, asset_check.get("pending_material") or [],
                         missing_segments, combined["failures"])
    manifest = {
        "capability": "pipeline.stable_film_assembly", "title": title,
        "status": status, "delivery_file": str(delivery),
        "delivery_note": note,
        # Probed duration of the delivered file (a tail pad, when
        # applied, makes it slightly longer than the planned total).
        "duration_sec": round(float((qc_report.get("probe") or {}).get("duration_sec", total_sec)), 3),
        "planned_duration_sec": round(total_sec, 3),
        "gates": combined["gates"], "failed_gates": combined["failed_gates"],
        "missing_gates": combined["missing_gates"],
        "undetermined_gates": combined["undetermined_gates"],
        "pending_gates": combined["pending_gates"],
        "failures": combined["failures"],
        "pending_material": asset_check.get("pending_material") or [],
        "pending_shot_ids": asset_check.get("pending_shot_ids") or [],
        "generation_shot_ids": asset_check.get("generation_shot_ids") or [],
        "missing_segments": missing_segments,
        "segment_plan": plan, "segment_plan_error": plan_error,
        "line_capacity": capacity, "subtitle_events": len(events),
        "subtitle_resplits": sub["resplits"],
        "transcript_source": transcript_source,
        "motion_beat_ratio": motion_gate.get("real_change_ratio") if motion_gate else None,
        "motion_beat_count": motion_gate.get("beat_count") if motion_gate else None,
        "picture_change_rate": combined["picture_change_rate"],
        "safe_zone": safe_zone, "loudness": loudness,
        "tail_pad": tail_pad,
        "timeline_gate": timeline_gate_report,
        "critic_review": critic_review_report,
        "defect_scan": (qc_report or {}).get("defect_scan"),
        "defect_scan_status": ((qc_report or {}).get("defect_scan") or {}).get("status"),
        "cut_comparison": {
            "status": "planned_not_measured",
            "note": ("segment boundaries are not luminance cuts, so no "
                     "planned_cuts were supplied to the defect scan; "
                     "cut-vs-plan comparison needs real planned cuts "
                     "from the caller"),
        },
        "rendered_text": (qc_report or {}).get("rendered_text"),
        "ducking": ducking, "bgm": bool(bgm_path is not None),
        "subtitle_srt": srt_text,
        "cost": {"route": "free", "amount": 0, "currency": "CNY",
                 "note": "no paid channel used; spend ledger not charged by this module"},
        "pre_confirmation_stage": "pre_synthesis",
        "post_confirmation": "required before any release; see confirm_post_gate",
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "delivery_note.txt").write_text(
        note + "\n\nFailures / missing / undetermined:\n"
        + ("\n".join(f"- {f}" for f in combined["failures"]) or "- none")
        + f"\n\nPending material:\n"
        + ("\n".join(f"- {p}" for p in asset_check.get("pending_material") or []) or "- none")
        + "\n", encoding="utf-8")
    return {**manifest, "mp4": str(delivery)}


# ---------------------------------------------------------------- registry

def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    segments = params.get("segments")
    if not isinstance(segments, list) or not segments:
        raise CapabilityError("pipeline.stable_film_assembly: params.segments must be a non-empty list")
    if not params.get("voice_path"):
        raise CapabilityError("pipeline.stable_film_assembly: params.voice_path is required")
    result = assemble_film(
        title=str(params.get("title", "film")), segments=segments,
        voice_path=Path(params["voice_path"]), out_dir=out_dir,
        pre_confirmation=params.get("pre_confirmation"),
        registry=params.get("registry"), episode_id=str(params.get("episode_id", "episode1")),
        bgm_path=Path(params["bgm_path"]) if params.get("bgm_path") else None,
        glossary=params.get("glossary"),
        transcript_source=str(params.get("transcript_source", "script")),
        missing_segments=params.get("missing_segments"),
        fps=int(params.get("fps", 10)),
        width=int(params.get("width", 540)), height=int(params.get("height", 960)),
        base_name=str(params.get("base_name", "film")),
        timeline=params.get("timeline"),
        critic_review=params.get("critic_review"),
        bpm=float(params["bpm"]) if params.get("bpm") is not None else None,
        rendered_text_boxes=params.get("rendered_text_boxes"))
    if result["status"] in ("refused", "failed"):
        raise CapabilityError(
            f"pipeline.stable_film_assembly: assembly {result['status']}: {result.get('reasons') or result.get('failures')}")
    return CapabilityResult(
        mp4=str(result["mp4"]), duration_s=float(result["duration_sec"]),
        sha256=compute_sha256(Path(result["mp4"])),
        qa={"report_json": str(out_dir / "manifest.json"), "verdict": result["status"],
            "pass": result["status"] == "finished",
            "failed_checks": result["failed_gates"],
            "skipped_checks": result["missing_gates"] + result["undetermined_gates"]},
    )


def register_stable_film_pipeline_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="pipeline.stable_film_assembly",
            kind="video",
            aspects=["9:16", "16:9", "1:1"],
            params_schema={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "segments": {"type": "array"},
                    "voice_path": {"type": "string"},
                    "episode_id": {"type": "string"},
                    "bgm_path": {"type": "string"},
                    "transcript_source": {"type": "string"},
                    "fps": {"type": "integer", "exclusiveMinimum": 0},
                    "width": {"type": "integer", "exclusiveMinimum": 0},
                    "height": {"type": "integer", "exclusiveMinimum": 0},
                    "base_name": {"type": "string"},
                    "timeline": {"type": "object"},
                    "critic_review": {"type": "object"},
                    "bpm": {"type": "number", "exclusiveMinimum": 0},
                    "rendered_text_boxes": {"type": "array", "items": {"type": "object"}},
                },
                "required": ["segments", "voice_path"],
                "additionalProperties": True,
            },
            cpu_cost_hint=1.0,
            render=_render,
            description=(
                "Stable-film assembly pipeline (B1-B7 baseline): "
                "segment gate, asset-registry pending check, "
                "subtitle re-break with frame-measured safe zone, "
                "motion-beat gate over motion beats only, mix-recipe "
                "loudness (voice-only normalisation or run_mix with "
                "fixed ducking for BGM), pre-render timeline gate, "
                "critic-review record judgment (only ship passes; "
                "no record is a missing gate), and final QC always "
                "with the defect scan enabled (fail-closed when the "
                "scan did not run) plus the Otsu caption-bar text "
                "measurement, combined into one finished / partial / "
                "review verdict. Two strict confirmation points; "
                "missing segments and pending material are listed, "
                "never padded or hidden."
            ),
            line="pipeline",
        )
    )
    return ["pipeline.stable_film_assembly"]


register_stable_film_pipeline_capabilities_once()
