"""Q2 bad-clip regression corpus: physical defect verification.

Every check here drives real ``ffmpeg`` / ``ffprobe`` against the generated
clips and asserts the defect physically exists (blackdetect, silencedetect,
freezedetect, astats, signalstats, ssim, pixel statistics, stream start
times).  Nothing is mocked and the module does not import any omquality review
code - it only depends on the committed manifest and the generated mp4s.

The mp4s live in ``$HEVI_QA_CORPUS_DIR`` (default ``/tmp/hevi_qa_corpus``); if
they are missing the module regenerates them once.

Run::

    JWT_SECRET=test-secret-local .venv/bin/python -m pytest tests/qa_corpus -q
    JWT_SECRET=test-secret-local .venv/bin/python -m pytest tests/qa_corpus -q -m slow
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXDIR = Path(__file__).resolve().parents[1] / "fixtures" / "qa_corpus"
MANIFEST_PATH = FIXDIR / "manifest.json"
CORPUS_DIR = Path(os.environ.get("HEVI_QA_CORPUS_DIR", "/tmp/hevi_qa_corpus"))

sys.path.insert(0, str(FIXDIR))


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _ff(args: list[str]) -> str:
    return subprocess.run(
        ["ffmpeg", "-nostdin", "-hide_banner", "-nostats", *args],
        capture_output=True,
        text=True,
    ).stderr


def _probe(path: Path) -> dict:
    out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type,start_time,width,height",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return json.loads(out)


def black_intervals(path: Path, d: float = 0.1, pix_th: float = 0.10):
    err = _ff(
        ["-i", str(path), "-vf", f"blackdetect=d={d}:pix_th={pix_th}", "-an", "-f", "null", "-"]
    )
    return [
        (float(a), float(b)) for a, b in re.findall(r"black_start:([\d.]+) black_end:([\d.]+)", err)
    ]


def silence_intervals(path: Path, n: str = "-45dB", d: float = 0.4):
    err = _ff(["-i", str(path), "-af", f"silencedetect=n={n}:d={d}", "-vn", "-f", "null", "-"])
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", err)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", err)]
    return list(zip(starts, ends + [None] * (len(starts) - len(ends))))


def freeze_intervals(path: Path, n: str = "-60dB", d: float = 0.5):
    err = _ff(["-i", str(path), "-vf", f"freezedetect=n={n}:d={d}", "-an", "-f", "null", "-"])
    starts = [float(x) for x in re.findall(r"freeze_start: ([\d.]+)", err)]
    ends = [float(x) for x in re.findall(r"freeze_end: ([\d.]+)", err)]
    return list(zip(starts, ends + [None] * (len(starts) - len(ends))))


def astats_peak_db(path: Path) -> float:
    err = _ff(["-i", str(path), "-af", "astats=metadata=1", "-vn", "-f", "null", "-"])
    vals = [float(x) for x in re.findall(r"Peak level dB: (-?[\d.]+|-?inf)", err) if "inf" not in x]
    return max(vals) if vals else -120.0


def decode_audio(path: Path, sr: int = 44100) -> np.ndarray:
    """Decode the first audio stream to mono float64 (full scale = 1.0)."""
    raw = subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(path),
            "-ac",
            "1",
            "-ar",
            str(sr),
            "-f",
            "f32le",
            "-",
        ],
        capture_output=True,
    ).stdout
    return np.frombuffer(raw, dtype="<f4").astype(np.float64)


def impulse_count(x: np.ndarray, thresh: float = 0.15) -> int:
    """Count sample-to-sample jumps larger than ``thresh``.

    Pops/clicks are broadband transients: their first difference spikes far
    above anything a smooth tone + noise bed produces.  This is the detector
    the FIX asks for (a pops clip is *not* a clipping clip, so peak alone is
    the wrong signal).
    """
    return int((np.abs(np.diff(x)) > thresh).sum())


def longest_fullscale_run(x: np.ndarray, level: float = 0.99) -> int:
    """Length of the longest run of consecutive samples with |x| >= ``level``.

    A genuine clipping defect leaves several samples pinned at full scale in a
    row; a single isolated peak does not.  Returns 0 when no sample is pinned.
    """
    mask = np.abs(x) >= level
    if not mask.any():
        return 0
    edges = np.flatnonzero(np.diff(np.concatenate(([0], mask.astype(np.int8), [0]))))
    return int((edges[1::2] - edges[::2]).max())


def signalstats_avg(path: Path) -> dict:
    out = subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-nostats",
            "-i",
            str(path),
            "-vf",
            "signalstats,metadata=mode=print:file=-",
            "-an",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
    ).stdout
    vals: dict[str, list[float]] = {}
    for key in ("YMIN", "YMAX", "YAVG", "UAVG", "VAVG", "YDIF", "SATAVG"):
        found = [float(x) for x in re.findall(rf"signalstats\.{key}=(-?[\d.]+)", out)]
        if found:
            vals[key] = [round(sum(found) / len(found), 1)]
    return {k: v[0] for k, v in vals.items()}


def ssim_all(path: Path, ref: Path) -> float:
    err = _ff(["-i", str(path), "-i", str(ref), "-lavfi", "ssim", "-f", "null", "-"])
    m = re.findall(r"All:([\d.]+)", err)
    return float(m[-1]) if m else 0.0


def _gray_frames(path: Path, t: float, count: int = 3) -> list[np.ndarray]:
    """Decode ``count`` grayscale frames starting at ``t`` seconds."""
    raw = subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            str(t),
            "-i",
            str(path),
            "-frames:v",
            str(count),
            "-pix_fmt",
            "gray",
            "-f",
            "rawvideo",
            "-",
        ],
        capture_output=True,
    ).stdout
    n = len(raw) // (1280 * 720)
    return [
        np.frombuffer(raw[i * 1280 * 720 : (i + 1) * 1280 * 720], dtype=np.uint8).reshape(720, 1280)
        for i in range(n)
    ]


def _row_stdev(gray: np.ndarray) -> np.ndarray:
    return gray.astype(np.float64).std(axis=1)


def _gray_frame(path: Path, t: float) -> np.ndarray:
    raw = subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            str(t),
            "-i",
            str(path),
            "-frames:v",
            "1",
            "-pix_fmt",
            "gray",
            "-f",
            "rawvideo",
            "-",
        ],
        capture_output=True,
    ).stdout
    return np.frombuffer(raw[: 1280 * 720], dtype=np.uint8).reshape(720, 1280)


def _overlay_vs_base(path: Path, t: float, thresh: int = 40):
    """Pixels that ``path`` adds on top of ``base.mp4`` at time ``t``.

    Returns ``(total, right_edge, bottom_edge)``.  ``good_clean`` shares the
    testsrc2 base (so the base can be subtracted), which makes "does the
    burned subtitle stay inside the safe area?" a clean, base-independent
    test - a raw brightness threshold is useless here because testsrc2 itself
    is bright near the frame edges.
    """
    base = _gray_frame(CORPUS_DIR / "base.mp4", t)
    cur = _gray_frame(path, t)
    overlay = np.abs(cur.astype(np.int16) - base.astype(np.int16)) > thresh
    return int(overlay.sum()), int(overlay[:, -4:].sum()), int(overlay[-4:, :].sum())


def _clip_path(cid: str) -> Path:
    return CORPUS_DIR / f"{cid}.mp4"


def _window_overlap(a, b, tol: float = 1.2) -> bool:
    """Do intervals [a0,a1] and [b0,b1] overlap within ``tol`` seconds?"""
    return not (a[1] < b[0] - tol or a[0] > b[1] + tol)


# ---------------------------------------------------------------------------
# session fixture: make sure the corpus exists
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session", autouse=True)
def ensure_corpus():
    if not (_clip_path("good_clean").exists() and MANIFEST_PATH.exists()):
        import make_corpus

        make_corpus.main(["--no-determinism-check"])
    return CORPUS_DIR


# ---------------------------------------------------------------------------
# corpus integrity
# ---------------------------------------------------------------------------


def test_corpus_has_17_bad_and_1_good():
    man = _manifest()
    assert man["bad_clip_count"] >= 17, man["bad_clip_count"]
    assert man["clip_count"] == man["bad_clip_count"] + 1
    good = [c for c in man["clips"] if c["expected_failures"] == []]
    assert [c["id"] for c in good] == ["good_clean"]


def test_all_clips_ffprobe_valid():
    man = _manifest()
    for c in man["clips"]:
        p = _clip_path(c["id"])
        assert p.exists(), c["id"]
        info = _probe(p)
        kinds = {s["codec_type"] for s in info["streams"]}
        assert kinds == {"video", "audio"}, (c["id"], kinds)
        assert 13.0 <= float(info["format"]["duration"]) <= 15.0, c["id"]


def test_sha256_matches_manifest():
    man = _manifest()
    for c in man["clips"]:
        if not c["sha_stable"]:
            continue
        digest = hashlib.sha256(_clip_path(c["id"]).read_bytes()).hexdigest()
        assert digest == c["sha256"], c["id"]


@pytest.mark.slow
def test_generator_regenerates_matching_corpus(tmp_path):
    """Re-running the generator reproduces the committed clips byte-for-byte."""
    import make_corpus

    make_corpus.main(
        [
            "--out",
            str(tmp_path),
            "--no-determinism-check",
            "--manifest",
            str(tmp_path / "manifest.json"),
        ]
    )
    man = _manifest()
    for c in man["clips"]:
        if not c["sha_stable"]:
            continue
        digest = hashlib.sha256((tmp_path / f"{c['id']}.mp4").read_bytes()).hexdigest()
        assert digest == c["sha256"], c["id"]


# ---------------------------------------------------------------------------
# per-defect physical verification
# ---------------------------------------------------------------------------


def _expected(cid: str) -> dict:
    return next(c for c in _manifest()["clips"] if c["id"] == cid)


def test_noise_clips_have_high_ydif():
    """Full-frame and local glitch: YDIF (temporal luma difference) is high."""
    for cid, window in [("bad01_noise_full", (0.0, 14.0)), ("bad02_glitch_local", (4.0, 7.0))]:
        assert _expected(cid)["expected_failures"], cid
        sg = signalstats_avg(_clip_path(cid))
        assert sg["YDIF"] > 15.0, (cid, sg)
    # the clean clip is quiet by comparison
    assert signalstats_avg(_clip_path("good_clean"))["YDIF"] < 8.0


def _signalstats_window(path: Path, t0: float, t1: float) -> dict:
    """signalstats averages over just [t0, t1] seconds."""
    out = subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-nostats",
            "-ss",
            str(t0),
            "-t",
            str(t1 - t0),
            "-i",
            str(path),
            "-vf",
            "signalstats,metadata=mode=print:file=-",
            "-an",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
    ).stdout
    vals = {}
    for key in ("UAVG", "VAVG", "YAVG"):
        found = [float(x) for x in re.findall(rf"signalstats\.{key}=(-?[\d.]+)", out)]
        if found:
            vals[key] = round(sum(found) / len(found), 1)
    return vals


def test_green_clips_have_low_chroma():
    """Green frames have a depressed V channel (green suppresses red/blue).

    Two flavours are covered: ``bad05`` is a decoder-failure green
    (Y=U=V=0, so both chroma means collapse), while ``bad06`` paints RGB
    green (0,255,0) - bright, so only V is low (U stays around 44-54).  A
    green frame is therefore "VAVG well below the neutral ~126"; the
    decoder-green additionally has UAVG ~0.  ``bad06`` is measured inside its
    6-9 s defect window so the normal frames do not dilute the average.
    """
    full = signalstats_avg(_clip_path("bad05_green_full"))
    assert full["UAVG"] < 8.0 and full["VAVG"] < 8.0, full

    exp = _expected("bad06_green_local")
    t0, t1 = exp["defect_window_s"]
    win = _signalstats_window(_clip_path("bad06_green_local"), t0 + 0.3, t1 - 0.3)
    assert win["VAVG"] < 60.0, win

    good = signalstats_avg(_clip_path("good_clean"))
    assert good["VAVG"] > 100.0, good


def test_half_gray_bottom_is_flat():
    """Bottom half replaced with flat gray: its row-stdev collapses to ~0."""
    frames = _gray_frames(_clip_path("bad07_halfgray_bottom"), t=8.0)
    assert frames
    sd = _row_stdev(frames[0])
    bottom_flat = float((sd[360:] < 1.0).mean())
    top_flat = float((sd[:360] < 1.0).mean())
    assert bottom_flat > 0.95, bottom_flat
    assert top_flat < 0.2, top_flat


def test_black_silent_clip():
    p = _clip_path("bad08_black_silent")
    bl = black_intervals(p)
    si = silence_intervals(p)
    assert any(_window_overlap(iv, (0.0, 14.0)) for iv in bl), bl
    assert any(_window_overlap(iv, (0.0, 14.0)) for iv in si), si


def test_audio_silence_gap_window_matches():
    exp = _expected("bad09_audio_silence_gap")
    si = silence_intervals(_clip_path("bad09_audio_silence_gap"))
    assert si, "no silence detected"
    w = exp["defect_window_s"]
    assert any(_window_overlap(iv, w) for iv in si), (si, w)


def test_audio_clipping_and_pops():
    # bad10: +40 dB into a hard limiter -> several consecutive samples pinned
    # at full scale.  Assert the *run length*, not just the peak, so an
    # isolated high sample would not pass as clipping.
    clip = decode_audio(_clip_path("bad10_audio_clip"))
    assert astats_peak_db(_clip_path("bad10_audio_clip")) >= -0.1
    assert longest_fullscale_run(clip) >= 3, longest_fullscale_run(clip)

    # bad11: periodic pops/clicks are *transients*, so it must have many
    # impulses - but it must NOT be a clipping clip (peak < -1 dBFS, no
    # pinned samples).  The earlier square burst clipped the file.
    pops = decode_audio(_clip_path("bad11_audio_pops"))
    good = decode_audio(_clip_path("good_clean"))
    n_pops = impulse_count(pops)
    n_good = impulse_count(good)
    assert n_pops > 20, n_pops
    assert n_good == 0, n_good
    assert astats_peak_db(_clip_path("bad11_audio_pops")) < -1.0
    assert longest_fullscale_run(pops) == 0, longest_fullscale_run(pops)

    # the clean clip never clips
    assert astats_peak_db(_clip_path("good_clean")) < -1.0


def _caption_height(gray: np.ndarray) -> int:
    """Number of rows containing caption glyph pixels (bright on the grey base)."""
    return int(((gray > 200).sum(axis=1) > 2).sum())


def test_subtitle_out_of_frame_and_font_size():
    # out-of-frame: bright caption pixels touch the right frame edge
    edge = np.zeros(1280)
    for g in _gray_frames(_clip_path("bad12_subtitle_out_of_frame"), t=2.0, count=2):
        edge = np.maximum(edge, (g > 200).sum(axis=0))
    assert edge[-4:].sum() > 0, "caption does not reach the right edge"

    # font too small: glyph height < 2% of the frame height.
    small = _caption_height(_gray_frames(_clip_path("bad13_font_too_small"), t=2.0)[0])
    assert 0 < small < 0.02 * 720, small
    # bad12 (44 px font) shares the same grey base, so its glyph height is the
    # positive control: comfortably above the 2% floor.
    normal = _caption_height(_gray_frames(_clip_path("bad12_subtitle_out_of_frame"), t=2.0)[0])
    assert normal >= 0.02 * 720, normal
    assert normal > small


def test_asr_mismatch_metadata_and_audio():
    exp = _expected("bad14_asr_mismatch")
    assert exp["caption_text"] != exp["audio_text"]
    assert exp["audio_text_source"] == "espeak"
    # the audio track is real speech, not silence
    si = silence_intervals(_clip_path("bad14_asr_mismatch"), d=0.5)
    assert astats_peak_db(_clip_path("bad14_asr_mismatch")) > -20.0
    assert not (len(si) == 1 and si[0][1] is None and si[0][0] < 0.1), si
    # FIX item 4: bad14 must carry *only* the asr_mismatch defect - the caption
    # has to fit fully inside the frame (no smuggled subtitle.out_of_frame).
    edge = np.zeros(1280)
    for g in _gray_frames(_clip_path("bad14_asr_mismatch"), t=2.0, count=2):
        edge = np.maximum(edge, (g > 200).sum(axis=0))
    assert edge[-4:].sum() == 0, "bad14 caption reaches the right frame edge"


def test_frozen_mid_window_matches():
    exp = _expected("bad15_frozen_mid")
    fz = freeze_intervals(_clip_path("bad15_frozen_mid"))
    assert fz, "no freeze detected"
    assert any(_window_overlap(iv, exp["defect_window_s"]) for iv in fz), fz


def test_av_desync_offset():
    p = _clip_path("bad16_av_desync")
    info = _probe(p)
    starts = {s["codec_type"]: float(s["start_time"]) for s in info["streams"]}
    offset = starts["audio"] - starts["video"]
    assert offset >= 0.12, (starts, offset)
    # the clean clip is in sync
    good = _probe(_clip_path("good_clean"))
    gs = {s["codec_type"]: float(s["start_time"]) for s in good["streams"]}
    assert abs(gs["audio"] - gs["video"]) < 0.05


def test_letterbox_excess_bars():
    """Top and bottom black bars each exceed 15% of the frame height."""
    g = _gray_frames(_clip_path("bad17_letterbox_excess"), t=2.0, count=1)[0]
    dark = (g < 16).mean(axis=1)
    top = float((dark[:360] > 0.95).sum())
    bottom = float((dark[360:] > 0.95).sum())
    assert top >= 0.15 * 720, top
    assert bottom >= 0.15 * 720, bottom
    # the clean clip has no bars
    g = _gray_frames(_clip_path("good_clean"), t=2.0, count=1)[0]
    dark = (g < 16).mean(axis=1)
    assert float((dark > 0.95).sum()) < 0.02 * 720


def test_macroblock_clips_degrade_ssim():
    """FIX item 6: macroblocking must drop SSIM clearly below the clean clip.

    The old ``< 0.99`` bound was too loose (measured 0.933/0.888 for the bad
    clips, 0.989 for the clean one).  Require bad < 0.95 and clean > 0.98.
    """
    ref = CORPUS_DIR / "base.mp4"
    for cid in ("bad03_macroblock_qp51", "bad04_macroblock_mpeg2"):
        s = ssim_all(_clip_path(cid), ref)
        assert s < 0.95, (cid, s)
    assert ssim_all(_clip_path("good_clean"), ref) > 0.98


def test_clean_clip_has_no_defects():
    """FIX item 6: the clean clip must trip none of the detectors, including
    the ones the defect clips rely on - no silence, no caption overflow at the
    right/bottom edges, no letterbox bars."""
    p = _clip_path("good_clean")
    assert not black_intervals(p), "clean clip reported black"
    assert not freeze_intervals(p), "clean clip reported a freeze"
    assert not silence_intervals(p, n="-45dB", d=0.4), "clean clip reported silence"
    assert astats_peak_db(p) < -1.0
    sg = signalstats_avg(p)
    assert sg["UAVG"] > 30.0 and sg["VAVG"] > 30.0
    assert sg["YDIF"] < 8.0

    # no burned-subtitle pixels on the right or bottom frame edge (measured as
    # the overlay on top of the base, so testsrc2's own edge brightness is not
    # mistaken for a caption)
    total, right, bottom = _overlay_vs_base(p, 2.0)
    assert total > 100, f"subtitle overlay not found: {total}"
    assert right == 0, f"caption overflows the right edge ({right} px)"
    assert bottom == 0, f"caption overflows the bottom edge ({bottom} px)"
    # no letterbox bars (no dark full-width rows)
    dark = (_gray_frame(p, 2.0) < 16).mean(axis=1)
    assert float((dark > 0.95).sum()) == 0, "clean clip has black bars"
