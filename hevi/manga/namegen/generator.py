"""M1 分镜生成器 — layout, camera, pose, dialogue, effects, 180-degree gate."""

from __future__ import annotations

import math
from pathlib import Path

from ..common import PRNG, RenderSize, aspect_ratio_value
from . import ASPECTS, POSES, SHOT_SIZES, PITCHES, TILTS, EMOTIONS, BG_KINDS, Beat, Panel, Script, Storyboard

# ---------------------------------------------------------------------------
# Panel layout.  Given a page aspect and a beat count, produce non-overlapping
# panel rectangles on a fixed-resolution page.  Deterministic via PRNG.
# ---------------------------------------------------------------------------

# Base page long edge (px).  We keep a sane resolution for SVG/PNG export.
PAGE_LONG_EDGE = 1600


def _page_size(aspect: str) -> tuple[int, int]:
    ratio = aspect_ratio_value(aspect) if aspect in ASPECTS else ASPECTS.get(aspect, 0.8)
    if ratio >= 1:
        w = PAGE_LONG_EDGE
        h = int(round(PAGE_LONG_EDGE / ratio))
    else:
        h = PAGE_LONG_EDGE
        w = int(round(PAGE_LONG_EDGE * ratio))
    return w, h


def _grid_layout(n: int, w: int, h: int, rng: PRNG) -> list[tuple[int, int, int, int]]:
    """Return list of (x, y, w, h) rectangles laid out in a tidy grid.

    We pick columns/rows to best fit ``n`` panels with a 0.96 gutter margin.
    A little per-panel jitter (scaled by variation) keeps it from looking like
    a spreadsheet while staying deterministic and overlap-free.
    """
    # choose column count near sqrt
    cols = max(1, round(math.sqrt(n * (w / h))))
    cols = min(cols, n)
    rows = math.ceil(n / cols)
    margin = int(0.02 * min(w, h))
    gw = (w - 2 * margin) / cols
    gh = (h - 2 * margin) / rows
    rects: list[tuple[int, int, int, int]] = []
    idx = 0
    for r in range(rows):
        row_cols = min(cols, n - idx)
        for c in range(row_cols):
            pad = int(gw * 0.04)
            x = margin + c * gw + pad
            y = margin + r * gh + pad
            pw = gw - 2 * pad
            ph = gh - 2 * pad
            rects.append((int(x), int(y), int(pw), int(ph)))
            idx += 1
    return rects[:n]


def _camera(beat: Beat, rng: PRNG, variation: float) -> dict[str, Any]:
    shot = beat.shot if beat.shot in SHOT_SIZES else "medium"
    pitch = rng.choose(list(PITCHES))
    tilt = rng.choose(list(TILTS))
    mm = rng.choose([24, 35, 50, 85])
    # focal length derived from shot size as a baseline, jittered by variation
    shot_mm = {"establishing": 24, "wide": 28, "medium": 50, "close": 85, "extreme": 135}[shot]
    mm = int(shot_mm * (1.0 + (rng.next() - 0.5) * 0.2 * variation))
    return {
        "shot": shot,
        "pitch": pitch,
        "tilt": tilt,
        "mm": mm,
        "viewer_side": beat.camera_side,
    }


def _pose(beat: Beat, rng: PRNG) -> dict[str, Any]:
    pose = beat.pose if beat.pose in POSES else "idle"
    # x position across the panel floor line; deterministic
    x = round(rng.range(0.25, 0.75), 3)
    return {"pose": pose, "floor_x": x}


def _dialogue(beat: Beat) -> dict[str, Any] | None:
    if not beat.text:
        return None
    # Bubble shape driven by emotion (comicalizer-style).  Text is verbatim.
    shape = {
        "neutral": "rounded",
        "shout": "spiked",
        "sad": "teardrop",
        "happy": "cloud",
        "think": "cloud_thought",
        "whisper": "soft",
    }.get(beat.emotion, "rounded")
    return {
        "speaker": beat.speaker,
        "text": beat.text,           # original script sentence, never altered
        "emotion": beat.emotion,
        "shape": shape,
    }


def _effects(beat: Beat, rng: PRNG) -> list[str]:
    out: list[str] = []
    r = rng.next()
    if beat.emotion == "shout" or beat.action.startswith("run") or beat.pose == "run":
        out.append("speed_lines")
    if beat.emotion == "shout":
        out.append("concentration_lines")
    if rng.next() < 0.4:
        out.append("tone_dots")
    return out


def assign_read_order(panels: list[Panel], reading_direction: str) -> None:
    """Number panels in reading order: top->bottom, then L->R or R->L."""
    rtl = reading_direction in ("rtl", "right-to-left")
    # sort by row (y band) then column
    ordered = sorted(panels, key=lambda p: (p.y, -(p.x) if rtl else p.x))
    for i, p in enumerate(ordered, start=1):
        p.read_order = i


def axis_gate(panels: list[Panel], tol: float = 0.0) -> list[dict[str, Any]]:
    """180-degree rule check across adjacent panels (in reading order).

    Each beat carries ``camera_side`` (signed, in [-1, 1]).  Crossing the axis
    means the sign flips between two consecutive speaking/acting panels while
    both have a defined non-zero side.  A flip (sign change, magnitude above
    tol) is a violation.
    """
    violations: list[dict[str, Any]] = []
    ordered = sorted(panels, key=lambda p: p.read_order)
    prev = None
    prev_idx = None
    for p in ordered:
        side = p.beat.camera_side
        if prev is not None and abs(side) > tol and abs(prev) > tol:
            if (side > 0) != (prev > 0):
                violations.append(
                    {
                        "between": [prev_idx, p.index],
                        "prev_side": prev,
                        "side": side,
                        "kind": "axis_cross",
                    }
                )
        prev = side
        prev_idx = p.index
    return violations


def generate(script: Script, aspect: str, reading_direction: str, seed: str,
             variation: float = 0.3) -> Storyboard:
    """Build a full Storyboard from a Script deterministically."""
    global prev_panels
    prev_panels = {}
    if aspect not in ASPECTS:
        raise ValueError(f"unknown aspect {aspect!r}; choose from {list(ASPECTS)}")
    if not script.beats:
        raise ValueError("script has no beats")
    w, h = _page_size(aspect)
    rng = PRNG(seed)
    rects = _grid_layout(len(script.beats), w, h, rng)

    panels: list[Panel] = []
    for i, (beat, rect) in enumerate(zip(script.beats, rects), start=0):
        cam = _camera(beat, rng, variation)
        panel = Panel(
            index=i,
            x=rect[0], y=rect[1], w=rect[2], h=rect[3],
            beat=beat,
            camera=cam,
            characters=[_pose(beat, rng)],
            dialogue=_dialogue(beat),
            effects=_effects(beat, rng),
        )
        panels.append(panel)

    assign_read_order(panels, reading_direction)
    violations = axis_gate(panels)
    board = Storyboard(
        aspect=aspect,
        reading_direction=reading_direction,
        seed=seed,
        variation=variation,
        page_w=w,
        page_h=h,
        panels=panels,
        axis_violations=violations,
    )
    return board
