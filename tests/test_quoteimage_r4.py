"""quoteimage r4 FIX regression tests on REAL source frames (no mocks).

Sources are the E2E inputs on the host; tests skip when they are absent.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from hevi.layer4_legacy.quoteimage.oprim_impl.subtitle_text import (
    band_edge_cuts_text,
    band_text_mass,
    feathered_side_fill,
    refine_band,
    sentence_single_card,
    text_mask,
)
from hevi.layer4_legacy.quoteimage.oprim_impl.vendor_stitch import grab_frame

SHORTS_01 = Path("/data/soffy/projects/hevi-zero/out/shorts_clip/shorts_clip_01.mp4")
SHORTS_02 = Path("/data/soffy/projects/hevi-zero/out/shorts_clip/shorts_clip_02.mp4")


def _text_rows(frame: Image.Image) -> np.ndarray:
    m = text_mask(frame)
    rows = np.where(m.mean(axis=1) > 0.004)[0]
    return rows[rows > int(frame.height * 0.65)]  # subtitle area of these shorts (footage sits higher)


@pytest.mark.skipif(not SHORTS_01.exists(), reason="E2E source video not on this host")
def test_two_line_subtitle_band_is_refined_and_bad_cut_is_detected():
    # vid_2 defect: at 4.21s the subtitle has two lines ("TEENAGERS, THEY'VE / BEEN FLYING")
    frame = grab_frame(str(SHORTS_01), 4.21)
    rows = _text_rows(frame)
    assert rows.size, "expected burned-in subtitle rows in the lower half"
    h = frame.height
    full_top, full_bot = (rows[0] - 6) / h, (rows[-1] + 7) / h
    # the two caption lines are separated by a gap; the old band stopped after line 1
    gaps = np.where(np.diff(rows) > 6)[0]
    assert gaps.size, "expected a two-line subtitle"
    line1_bottom = (rows[gaps[0]] + 4) / h
    cut, val = band_edge_cuts_text(frame, full_top, line1_bottom)
    assert cut, f"band that drops the 2nd subtitle line not flagged (score={val})"
    # refining from the one-line band grows it over both lines → PASS
    top, bot = refine_band([frame], full_top, line1_bottom)
    assert bot >= (rows[-1] + 1) / h
    ok_cut, val2 = band_edge_cuts_text(frame, top, bot)
    assert not ok_cut, f"refined band still flagged (score={val2})"


@pytest.mark.skipif(not SHORTS_02.exists(), reason="E2E source video not on this host")
def test_rolling_caption_sentence_is_rejected_as_half_sentence():
    # vid_3 defect: "I was a second class midshipman at the ..." scrolls over several caption cards
    def grab(t: float):
        return grab_frame(str(SHORTS_02), t)

    frame = grab(2.14)
    rows = _text_rows(frame)
    h = frame.height
    top, bot = (rows[0] - 6) / h, (rows[-1] + 7) / h
    single, _ = sentence_single_card(grab, 1.9, 6.4, top, bot)
    assert single is False


@pytest.mark.skipif(not SHORTS_01.exists(), reason="E2E source video not on this host")
def test_band_text_mass_separates_subtitled_and_clean_frames():
    frame = grab_frame(str(SHORTS_01), 4.21)
    rows = _text_rows(frame)
    h = frame.height
    top, bot = (rows[0] - 6) / h, (rows[-1] + 7) / h
    assert band_text_mass(frame, top, bot) > 0.0015
    # the same band on a synthetic clean frame (no glyphs) reads as empty
    clean = Image.new("RGB", frame.size, (40, 60, 90))
    assert band_text_mass(clean, top, bot) < 0.0015


def test_side_fill_has_no_hard_vertical_seam():
    # dark caption box in the middle, light grey clutter at the sides (the r4 #4 look)
    w, h = 720, 80
    arr = np.full((h, w, 3), 200, np.uint8)
    arr[:, 200:520] = (20, 22, 40)
    band = Image.fromarray(arr)
    out = np.asarray(feathered_side_fill(band, 220, 500)).astype(int)
    # no column-to-column jump anywhere in the filled band
    jumps = np.abs(np.diff(out, axis=1)).max()
    assert jumps < 40, f"hard seam of {jumps} levels remains"


@pytest.mark.skipif(not SHORTS_01.exists(), reason="E2E source video not on this host")
def test_short_sentence_inside_cross_sentence_card_is_rejected():
    # vid_2 r5 defect: ASR "Let's see." (6.5–6.88s) sits inside the card "LET'S SEE, LET'S FIND",
    # which is still on screen while the next sentence ("Let's find that…") is spoken.
    def grab(t: float):
        return grab_frame(str(SHORTS_01), t)

    frame = grab(6.6)
    rows = _text_rows(frame)
    h = frame.height
    top, bot = (rows[0] - 6) / h, (rows[-1] + 7) / h
    alone, _ = sentence_single_card(grab, 6.5, 6.88, top, bot)
    assert alone is True  # within its own span the card does not change …
    single, _ = sentence_single_card(grab, 6.5, 6.88, top, bot, neighbor_times=[7.05])
    assert single is False  # … but the neighbour is spoken over the same card → half sentence


@pytest.mark.skipif(not SHORTS_02.exists(), reason="E2E source video not on this host")
def test_complete_single_card_sentence_passes():
    # vid_3: "You guys inspired me." (0–1.6s) is one complete caption card of its own
    def grab(t: float):
        return grab_frame(str(SHORTS_02), t)

    frame = grab(0.64)
    rows = _text_rows(frame)
    h = frame.height
    top, bot = (rows[0] - 6) / h, (rows[-1] + 7) / h
    single, best = sentence_single_card(grab, 0.0, 1.6, top, bot, neighbor_times=[2.2])
    assert single is True and best is not None
