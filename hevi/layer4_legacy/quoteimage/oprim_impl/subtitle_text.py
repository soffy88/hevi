"""Burned-in subtitle text geometry helpers (clean-room, Hevi).

All helpers work on a *text mask*: bright, high local-contrast pixels in the
lower part of the frame, which is what burned-in subtitles look like (white or
light-coloured glyphs with an outline / shadow / dark box behind them).

Used by quoteimage to
- grow a detected subtitle band so it covers every line of a multi-line
  subtitle (``refine_band``),
- detect a crop line that slices through glyphs (``band_edge_cuts_text``),
- tell whether a subtitle card stays on screen for a whole spoken sentence
  (``sentence_single_card``), and
- find a hero frame whose subtitle band is empty (``pick_clean_hero_time``).
"""
from __future__ import annotations

from typing import Callable, Sequence

import numpy as np
from PIL import Image, ImageChops, ImageFilter

LOWER_START = 0.45  # subtitles live in the lower part of the frame
ROW_TEXT_DENSITY = 0.004  # fraction of a row's pixels that must be glyph ink
EDGE_CUT_DENSITY = 0.006


def text_mask(img: Image.Image) -> np.ndarray:
    """Boolean (h, w) mask of subtitle-like glyph pixels."""
    gray = img.convert("L")
    contrast = ImageChops.subtract(gray, gray.filter(ImageFilter.MinFilter(5)))
    g = np.asarray(gray)
    c = np.asarray(contrast)
    return (g >= 185) & (c >= 55)


def _row_density(mask: np.ndarray) -> np.ndarray:
    return mask.mean(axis=1)


def refine_band(
    frames: Sequence[Image.Image], top: float, bottom: float, max_grow: float = 1.1
) -> tuple[float, float]:
    """Grow (top, bottom) so the band covers every subtitle line in every frame.

    For each frame the rows with glyph ink are found; starting from the rows that
    already lie inside the band, the band grows up/down through text rows that
    are separated by at most a line gap.  The result is the union over frames,
    padded a little so the crop line never touches a glyph.
    """
    if not frames:
        return top, bottom
    h = frames[0].height
    lo_limit = int(h * LOWER_START)
    gap = max(4, int(h * 0.03))
    y_top, y_bot = int(h * top), int(h * bottom)
    new_top, new_bot = y_top, y_bot
    # a multi-line subtitle adds about one more line of the same height: cap the growth
    # so unrelated text (slide titles, next-line previews) is not swallowed into the band
    grow = max(4, int((y_bot - y_top) * max_grow))
    up_limit, down_limit = max(lo_limit, y_top - grow), min(h, y_bot + grow)
    for fr in frames:
        dens = _row_density(text_mask(fr))
        text = dens > ROW_TEXT_DENSITY
        text[:lo_limit] = False
        rows = np.where(text[y_top:y_bot])[0]
        if rows.size == 0:
            continue
        a, b = y_top + int(rows[0]), y_top + int(rows[-1])
        # grow upward
        y = a - 1
        last = a
        while y >= up_limit and last - y <= gap:
            if text[y]:
                last = y
            y -= 1
        a = last
        # grow downward
        y = b + 1
        last = b
        while y < down_limit and y - last <= gap:
            if text[y]:
                last = y
            y += 1
        b = last
        new_top = min(new_top, a)
        new_bot = max(new_bot, b + 1)
    pad = max(4, int(h * 0.012))
    new_top = max(lo_limit, new_top - pad)
    new_bot = min(h, new_bot + pad)
    return round(new_top / h, 4), round(new_bot / h, 4)


def band_edge_cuts_text(frame: Image.Image, top: float, bottom: float) -> tuple[bool, float]:
    """True when the band's crop lines run through glyphs OR leave a subtitle line outside.

    Two failure shapes are caught: a crop line slicing through glyph ink, and a
    multi-line subtitle whose next/previous line sits just outside the band
    (within one line gap) — the vid_2 "second line covered by the next strip" defect.
    """
    h = frame.height
    dens = _row_density(text_mask(frame))
    worst = 0.0
    for y in (int(h * top), int(h * bottom)):
        if 0 < y < h:
            worst = max(worst, float(dens[max(0, y - 2): min(h, y + 2)].mean()))
    gap = max(4, int(h * 0.03))
    lo = int(h * LOWER_START)
    y_top, y_bot = int(h * top), int(h * bottom)
    outside = np.concatenate([dens[max(lo, y_top - gap): max(lo, y_top - 1)], dens[min(h, y_bot + 1): min(h, y_bot + gap)]])
    missed = float((outside > ROW_TEXT_DENSITY * 2).mean()) if outside.size else 0.0
    if missed > 0.15:
        worst = max(worst, EDGE_CUT_DENSITY + missed)
    return worst > EDGE_CUT_DENSITY, round(worst, 4)


def band_text_mass(frame: Image.Image, top: float, bottom: float) -> float:
    h = frame.height
    m = text_mask(frame)[int(h * top): int(h * bottom)]
    return float(m.mean()) if m.size else 0.0


def _band_mask(frame: Image.Image, top: float, bottom: float) -> np.ndarray:
    h = frame.height
    return text_mask(frame)[int(h * top): int(h * bottom)]


def sentence_single_card(
    grab: Callable[[float], Image.Image],
    start: float,
    end: float,
    top: float,
    bottom: float,
    step: float = 0.4,
) -> tuple[bool, float | None]:
    """Does one subtitle card stay on screen for the whole sentence?

    Samples the band through ``[start, end]``; when the glyph layout changes
    (IoU < 0.5 between two inked samples) the sentence is shown as several
    rolling caption fragments, so a single frame would show only part of it.
    Returns (single_card, best_time) where best_time is the sample with the most ink.
    """
    t = start + 0.1
    ts = []
    while t <= max(start + 0.1, end - 0.1) + 1e-6:
        ts.append(round(t, 2))
        t += step
    masks, best_t, best_mass = [], None, 0.0
    for tt in ts:
        try:
            m = _band_mask(grab(tt), top, bottom)
        except BaseException:
            continue
        mass = float(m.mean()) if m.size else 0.0
        if mass > best_mass:
            best_mass, best_t = mass, tt
        masks.append(m if mass > 0.002 else None)
    inked = [m for m in masks if m is not None]
    if not inked:
        return False, None
    for a, b in zip(inked, inked[1:]):
        inter = np.logical_and(a, b).sum()
        union = np.logical_or(a, b).sum()
        if union and inter / union < 0.5:
            return False, best_t
    return True, best_t


def pick_clean_hero_time(
    grab: Callable[[float], Image.Image],
    near: float,
    duration: float,
    top: float,
    bottom: float,
    max_offset: float = 12.0,
    step: float = 0.5,
    empty_mass: float = 0.0015,
) -> float | None:
    """Closest time to ``near`` whose subtitle band holds (almost) no glyph ink."""
    offsets = [0.0]
    k = step
    while k <= max_offset:
        offsets += [-k, k]
        k += step
    for off in offsets:
        t = near + off
        if t < 0.2 or t >= duration - 0.2:
            continue
        try:
            if band_text_mass(grab(t), top, bottom) < empty_mass:
                return round(t, 2)
        except BaseException:
            continue
    return None


def feathered_side_fill(band: Image.Image, left_safe: int, right_safe: int, ramp: int = 24) -> Image.Image:
    """Replace the band outside [left_safe, right_safe) without hard edges.

    Each row is extended with the colour found right at the safe edge (median of
    a narrow column just inside it), so the fill continues the band's own
    background row by row and no rectangular colour block / vertical seam appears.
    """
    arr = np.asarray(band.convert("RGB")).astype(np.float32)
    h, w, _ = arr.shape
    out = arr.copy()
    col = 6
    if left_safe > 0:
        edge = np.median(arr[:, left_safe: min(w, left_safe + col)], axis=1)  # (h, 3)
        out[:, :left_safe] = edge[:, None, :]
    if right_safe < w:
        edge = np.median(arr[:, max(0, right_safe - col): right_safe], axis=1)
        out[:, right_safe:] = edge[:, None, :]
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))
