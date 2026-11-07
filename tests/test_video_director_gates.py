"""Unit tests for the video-director P0 grafts (clean-room rewrites).

Covers qa.timeline_gate, the qa.final_qc_gate defect scan,
qa.rendered_text_measure, qa.critic_review and qa.facts_discipline:
at least one positive and one negative case per capability, plus
the undetermined/skipped branches.
"""

from __future__ import annotations

import glob
import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

from hevi.capabilities.critic_review import (
    check_revision_pixel_identity,
    record_critic_review,
)
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.facts_discipline import check_facts
from hevi.capabilities.otsu_text import measure_rendered_text
from hevi.capabilities.timeline_gate import check_timeline

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe required",
)


# ---------------------------------------------------------------- timeline

def _clean_timeline() -> dict:
    return {
        "meta": {"w": 1920, "h": 1080, "fps": 30, "dur": 6.0,
                 "clock": "music", "bpm": 120},
        "scenes": [{"start": 0.0, "end": 3.0}, {"start": 3.0, "end": 6.0}],
        "beats": [0.0, 1.5, 3.0, 4.5],
        "cuts": [3.0],
        "texts": [
            {"role": "hook", "text": "Hook line here", "start": 0.0,
             "end": 2.5, "px": 96},
            {"role": "term", "text": "Term word", "start": 0.5,
             "end": 2.5, "px": 60},
        ],
        "terms": [{"term": "alpha", "said": True, "shown": True}],
        "vo_words": [{"t": 0.5}, {"t": 1.0}, {"t": 1.5}],
        "captions": [{"start": 0.0, "end": 1.2, "words": 3}],
        "sfx": [{"at": 1.5}],
        "hero": {"t": 4.0},
        "silences": [{"start": 0.0, "end": 0.6}],
    }


def test_timeline_clean_passes() -> None:
    report = check_timeline(_clean_timeline())
    assert report["verdict"] == "pass"
    assert report["errors"] == []


def test_timeline_bad_meta_and_clock_fail() -> None:
    timeline = _clean_timeline()
    timeline["meta"]["dur"] = 0
    timeline["meta"]["clock"] = "banana"
    report = check_timeline(timeline)
    assert report["verdict"] == "fail"
    assert any("META_DUR" in e for e in report["errors"])
    assert any("META_CLOCK" in e for e in report["errors"])


def test_timeline_music_without_bpm_fails() -> None:
    timeline = _clean_timeline()
    del timeline["meta"]["bpm"]
    report = check_timeline(timeline)
    assert any("META_BPM" in e for e in report["errors"])


def test_timeline_loop_must_be_whole_bars() -> None:
    timeline = _clean_timeline()
    timeline["meta"]["loop"] = True
    # 6.0s at 120bpm = 3 bars of 2.0s: passes.
    assert check_timeline(timeline)["verdict"] == "pass"
    timeline["meta"]["dur"] = 6.5
    timeline["scenes"] = [{"start": 0.0, "end": 3.0}, {"start": 3.0, "end": 6.5}]
    report = check_timeline(timeline)
    assert any("LOOP_BARS" in e for e in report["errors"])


def test_timeline_scene_gap_and_tail_fail() -> None:
    timeline = _clean_timeline()
    timeline["scenes"] = [{"start": 0.0, "end": 2.9}, {"start": 3.0, "end": 6.0}]
    report = check_timeline(timeline)
    assert any("SCENE_GAP" in e for e in report["errors"])
    timeline["scenes"] = [{"start": 0.0, "end": 3.0}, {"start": 3.0, "end": 5.0}]
    report = check_timeline(timeline)
    assert any("SCENE_TAIL" in e for e in report["errors"])


def test_timeline_beat_cut_outside_duration_and_sfx_without_beat() -> None:
    timeline = _clean_timeline()
    timeline["beats"] = [0.0, 7.0]
    timeline["cuts"] = [9.0]
    timeline["sfx"] = [{"at": 2.7}]
    report = check_timeline(timeline)
    assert any(e.startswith("BEAT_") for e in report["errors"])
    assert any(e.startswith("CUT_") for e in report["errors"])
    assert any("SFX_" in e for e in report["errors"])


def test_timeline_hook_late_fails_and_waiver_warns() -> None:
    timeline = _clean_timeline()
    timeline["texts"][0]["start"] = 3.1
    timeline["texts"][0]["end"] = 5.5
    report = check_timeline(timeline)
    assert report["verdict"] == "fail"
    assert any("hook" in e.lower() for e in report["errors"])
    timeline["meta"]["hookWaiver"] = True
    report = check_timeline(timeline)
    assert report["verdict"] == "pass"
    assert any("hook" in w.lower() for w in report["warnings"])


def test_timeline_px_floor_and_short_edge_scaling() -> None:
    timeline = _clean_timeline()
    timeline["texts"][0]["px"] = 50
    report = check_timeline(timeline)
    assert any("below floor" in e for e in report["errors"])
    # Same 30px hook on a 360p short edge scales the 84px floor to 28px.
    small = _clean_timeline()
    small["meta"]["w"] = 640
    small["meta"]["h"] = 360
    small["texts"][0]["px"] = 30
    report = check_timeline(small)
    assert not any("below floor" in e for e in report["errors"])


def test_timeline_term_neither_said_nor_shown_fails() -> None:
    timeline = _clean_timeline()
    timeline["terms"] = [{"term": "alpha", "said": False, "shown": False}]
    report = check_timeline(timeline)
    assert any("neither said nor shown" in e for e in report["errors"])
    timeline["terms"] = [{"term": "alpha", "said": True, "shown": False}]
    report = check_timeline(timeline)
    assert report["verdict"] == "pass"
    assert any("said but not shown" in w for w in report["warnings"])


def test_timeline_vo_not_increasing_fails() -> None:
    timeline = _clean_timeline()
    timeline["vo_words"] = [{"t": 1.0}, {"t": 1.0}]
    report = check_timeline(timeline)
    assert any("not increasing" in e for e in report["errors"])


def test_timeline_warnings_cover_caption_hero_silence_and_estimated() -> None:
    timeline = _clean_timeline()
    timeline["captions"] = [{"start": 0.0, "end": 1.0, "words": 10}]
    timeline["hero"] = {"t": 1.0}
    timeline["silences"] = [{"start": 0.0, "end": 0.2}]
    timeline["vo_words"] = [{"t": 0.5, "estimated": True}, {"t": 1.0}]
    timeline["terms"] = []
    report = check_timeline(timeline)
    assert report["verdict"] == "pass"
    joined = " ".join(report["warnings"])
    assert "words/sec" in joined
    assert "HERO_EARLY" in joined
    assert "SILENCE_SHORT" in joined
    assert "ESTIMATED" in joined
    assert "TERMS_MISSING" in joined


# ------------------------------------------------------------- defect scan

def _write_video(path: Path, frame_fn, fps: int, duration: float,
                 size: tuple[int, int] = (160, 90)) -> Path:
    import numpy as np

    width, height = size
    count = max(1, round(duration * fps))
    proc = subprocess.Popen(
        ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
         "-s", f"{width}x{height}", "-r", str(fps), "-i", "-",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", str(path)],
        stdin=subprocess.PIPE,
    )
    assert proc.stdin is not None
    xs = np.arange(width, dtype=np.float64)
    ys = np.arange(height, dtype=np.float64)[:, None]
    for i in range(count):
        t = i / fps
        img = frame_fn(t, i, xs, ys)
        proc.stdin.write(img.astype(np.uint8).tobytes())
    proc.stdin.close()
    assert proc.wait() == 0
    return path


def _gradient(t: float, i: int, xs, ys, shift: float = 0.0):
    import numpy as np

    # Smooth gradient plus a slowly moving bar: steady small
    # frame-to-frame change, so abrupt shifts stand out as cuts.
    g = np.clip(xs[None, :] * 0.9 + ys * 0.4 + shift, 0, 200)
    g = g.copy()
    bar_x = (i * 3) % 140
    g[:, bar_x:bar_x + 20] = np.clip(g[:, bar_x:bar_x + 20] + 55, 0, 255)
    return np.stack([g, np.clip(g * 0.8 + 20, 0, 255),
                     np.clip(g * 0.6 + 40, 0, 255)], axis=2)


def test_defect_scan_clean_passes_and_default_off_has_no_defect_checks(tmp_path: Path) -> None:
    from hevi.capabilities.final_qc import run_final_qc

    media = _write_video(tmp_path / "clean.mp4", _gradient, 30, 3.0)
    report = run_final_qc(media, defect_scan=True, planned_cuts=[],
                          subtitle_text="hello", work_dir=tmp_path / "work")
    assert report["checks"]["defect_flash"]["pass"] is True
    assert report["checks"]["defect_unplanned_cuts"]["pass"] is None
    assert report["checks"]["defect_loop_seam"]["pass"] is None
    assert report["defect_scan"]["status"] == "pass"
    plain = run_final_qc(media, subtitle_text="hello", work_dir=tmp_path / "work2")
    assert not any(name.startswith("defect_") for name in plain["checks"])
    assert plain["defect_scan"] is None


def test_defect_scan_flash_detected(tmp_path: Path) -> None:
    from hevi.capabilities.final_qc import run_final_qc

    def with_flash(t, i, xs, ys):
        import numpy as np

        if 1.0 <= t < 1.134:
            return np.full((ys.shape[0], xs.shape[0], 3), 255, dtype=np.float64)
        return _gradient(t, i, xs, ys)

    media = _write_video(tmp_path / "flash.mp4", with_flash, 30, 3.0)
    report = run_final_qc(media, defect_scan=True, subtitle_text="hello",
                          work_dir=tmp_path / "work")
    assert report["checks"]["defect_flash"]["pass"] is False
    assert report["defect_scan"]["flash"], "flash frame must be listed"
    assert abs(report["defect_scan"]["flash"][0]["t_sec"] - 1.067) < 0.15


def test_defect_scan_unplanned_cut_detected(tmp_path: Path) -> None:
    from hevi.capabilities.final_qc import run_final_qc

    def with_cuts(t, i, xs, ys):
        shift = 0.0 if t < 1.0 else (80.0 if t < 2.0 else 160.0)
        return _gradient(t, i, xs, ys, shift=shift)

    media = _write_video(tmp_path / "cuts.mp4", with_cuts, 30, 3.0)
    report = run_final_qc(media, defect_scan=True, planned_cuts=[2.0],
                          subtitle_text="hello", work_dir=tmp_path / "work")
    assert report["checks"]["defect_unplanned_cuts"]["pass"] is False
    assert report["defect_scan"]["unplanned_cuts"], "cut near 1.0s must be unplanned"
    assert report["defect_scan"]["missing_cuts"] == []


def test_defect_scan_frozen_is_a_warning(tmp_path: Path) -> None:
    from hevi.capabilities.final_qc import run_final_qc

    frozen_frame = _gradient(0.5, 15, __import__("numpy").arange(160, dtype=float),
                             __import__("numpy").arange(90, dtype=float)[:, None])

    def with_frozen(t, i, xs, ys):
        if 0.5 <= t < 1.7:
            return frozen_frame
        return _gradient(t, i, xs, ys)

    media = _write_video(tmp_path / "frozen.mp4", with_frozen, 30, 3.0)
    report = run_final_qc(media, defect_scan=True, subtitle_text="hello",
                          work_dir=tmp_path / "work")
    assert report["defect_scan"]["frozen"], "1.2s frozen run must be recorded"
    assert report["checks"]["defect_frozen"]["pass"] is True
    assert any("frozen" in w for w in report["defect_scan"]["warnings"])


def test_defect_scan_short_film_is_skipped_not_passed(tmp_path: Path) -> None:
    from hevi.capabilities.final_qc import run_final_qc

    media = _write_video(tmp_path / "short.mp4", _gradient, 30, 0.2)
    report = run_final_qc(media, defect_scan=True, subtitle_text="hello",
                          work_dir=tmp_path / "work")
    assert report["defect_scan"]["status"] == "skipped"
    for name in ("defect_flash", "defect_unplanned_cuts", "defect_frozen",
                 "defect_flat", "defect_loop_seam"):
        assert report["checks"][name]["pass"] is None


def test_defect_scan_loop_seam(tmp_path: Path) -> None:
    from hevi.capabilities.final_qc import run_final_qc
    import numpy as np

    xs = np.arange(160, dtype=np.float64)
    ys = np.arange(90, dtype=np.float64)[:, None]
    base = (xs[None, :] * 1.2 + ys * 0.8) % 256
    base_rgb = np.stack([base, (base + 80) % 256, (base + 160) % 256], axis=2)

    def loop_frame(t, i, _xs, _ys):
        frame = base_rgb.copy()
        angle = 2 * np.pi * t / 3.0
        cx = int(80 + 40 * np.cos(angle))
        cy = int(45 + 25 * np.sin(angle))
        frame[max(0, cy - 5):cy + 5, max(0, cx - 5):cx + 5] = 255
        return frame

    media = _write_video(tmp_path / "loop.mp4", loop_frame, 30, 3.0)
    report = run_final_qc(media, defect_scan=True, is_loop=True,
                          subtitle_text="hello", work_dir=tmp_path / "work")
    assert report["checks"]["defect_loop_seam"]["pass"] is True


# ------------------------------------------------------------------- otsu

def _font(size: int) -> ImageFont.FreeTypeFont:
    candidates = glob.glob("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
    if not candidates:
        pytest.skip("DejaVu font not available")
    return ImageFont.truetype(candidates[0], size)


def _text_image(size: int, colour: tuple[int, int, int], tmp_path: Path) -> tuple[Path, list[int]]:
    img = Image.new("RGB", (640, 360), "white")
    draw = ImageDraw.Draw(img)
    font = _font(size)
    bbox = draw.textbbox((20, 100), "HELLO", font=font)
    draw.text((20, 100), "HELLO", font=font, fill=colour)
    path = tmp_path / f"text_{size}_{colour[0]}.png"
    img.save(path)
    return path, list(bbox)


def test_otsu_known_size_passes(tmp_path: Path) -> None:
    path, bbox = _text_image(100, (0, 0, 0), tmp_path)
    report = measure_rendered_text(path, bbox, "hook", at_sec=0.0)
    assert report["status"] == "pass"
    assert report["pass"] is True
    assert 85 <= report["font_px"] <= 115
    assert report["contrast_ratio"] > 7.0


def test_otsu_small_size_and_low_contrast_fail(tmp_path: Path) -> None:
    path, bbox = _text_image(20, (0, 0, 0), tmp_path)
    report = measure_rendered_text(path, bbox, "hook", at_sec=0.0)
    assert report["status"] == "fail"
    path, bbox = _text_image(100, (128, 128, 128), tmp_path)
    report = measure_rendered_text(path, bbox, "hook", at_sec=0.0)
    assert report["status"] == "fail"
    assert report["contrast_ratio"] < 7.0


def test_otsu_undetermined_without_box_or_timestamp(tmp_path: Path) -> None:
    path, bbox = _text_image(100, (0, 0, 0), tmp_path)
    report = measure_rendered_text(path, None, "hook", at_sec=0.0)
    assert report["status"] == "undetermined" and report["pass"] is None
    report = measure_rendered_text(path, bbox, "hook")
    assert report["status"] == "undetermined" and report["pass"] is None


# ----------------------------------------------------------------- critic

def _review(**overrides) -> dict:
    axes = {
        axis: {"score": 9, "evidence": f"frame 12 at 0:0{i + 1}s"}
        for i, axis in enumerate(
            ["Hook", "Clarity", "Readability", "Motion quality",
             "Rhythm and variety", "Composition and look", "Continuity",
             "Truth", "Sound sync"]
        )
    }
    review = {"axes": axes, "defects": [], "fix_round": 0}
    review.update(overrides)
    return review


def test_critic_ship_and_one_more_pass() -> None:
    assert record_critic_review(_review())["verdict"] == "ship"
    review = _review()
    review["axes"]["Clarity"] = {"score": 7, "evidence": "frame 3 at 0:01s"}
    assert record_critic_review(review)["verdict"] == "one_more_pass"
    review = _review(defects=[{"severity": "P0", "description": "hook unreadable"}])
    assert record_critic_review(review)["verdict"] == "one_more_pass"


def test_critic_fix_round_limit_and_invalid_records() -> None:
    assert record_critic_review(_review(fix_round=2))["verdict"] == "fail"
    assert record_critic_review(_review(fix_round=1))["verdict"] == "ship"
    review = _review()
    review["axes"]["Hook"] = {"score": 9}
    with pytest.raises(CapabilityError):
        record_critic_review(review)
    review = _review()
    review["axes"]["Hook"] = {"score": 11, "evidence": "frame 1 at 0:01s"}
    with pytest.raises(CapabilityError):
        record_critic_review(review)
    review = _review()
    del review["axes"]["Truth"]
    with pytest.raises(CapabilityError):
        record_critic_review(review)


def test_critic_defects_sorted_p0_first() -> None:
    review = _review(defects=[
        {"severity": "P2", "description": "minor"},
        {"severity": "P0", "description": "blocking"},
        {"severity": "P1", "description": "major"},
    ])
    report = record_critic_review(review)
    assert [d["severity"] for d in report["defects"]] == ["P0", "P1", "P2"]


def _frame_dirs(tmp_path: Path, label: str, changed_index: int | None = None,
                changed_value: int = 200) -> tuple[Path, Path]:
    before, after = tmp_path / f"{label}_before", tmp_path / f"{label}_after"
    before.mkdir(parents=True, exist_ok=True)
    after.mkdir(parents=True, exist_ok=True)
    for i in range(20):
        img = Image.new("RGB", (8, 8), (10, 20, 30))
        img.save(before / f"frame_{i:06d}.png")
        img2 = Image.new("RGB", (8, 8), (10, 20, 30))
        if changed_index is not None and i == changed_index:
            img2 = Image.new("RGB", (8, 8), (changed_value, 20, 30))
        img2.save(after / f"frame_{i:06d}.png")
    return before, after


def test_revision_pixel_identity() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        before, after = _frame_dirs(tmp, "clean")
        report = check_revision_pixel_identity(before, after, [], fps=10)
        assert report["status"] == "pass"
        # Change outside the fix range fails and names the frame.
        before, after = _frame_dirs(tmp, "changed", changed_index=15)
        report = check_revision_pixel_identity(
            before, after, [[0.0, 1.0]], fps=10)
        assert report["status"] == "fail"
        assert report["changed_frames"][0]["file"] == "frame_000015.png"
        # Same change inside the fix range is allowed.
        report = check_revision_pixel_identity(
            before, after, [[1.0, 2.0]], fps=10)
        assert report["status"] == "pass"
        # A 1-step difference within tolerance passes.
        report = check_revision_pixel_identity(
            before, after, [[0.0, 1.0]], fps=10, tolerance=200)
        assert report["status"] == "pass"
        # MP4 inputs are rejected, not diffed.
        with pytest.raises(CapabilityError):
            check_revision_pixel_identity(tmp / "a.mp4", tmp / "b.mp4", [], fps=10)


# ------------------------------------------------------------------ facts

def test_facts_moving_counter_rule() -> None:
    report = check_facts(["计数器上升，显示 4705 名订阅者。"], as_of="2026-10")
    assert report["verdict"] == "fail"
    assert report["failures"][0]["rule"] == "moving_counter_no_value_label"
    assert "4705" in report["failures"][0]["sentence"]
    report = check_facts(["计数器停稳后显示 4705 名订阅者。"], as_of="2026-10")
    assert report["verdict"] == "pass"


def test_facts_unfinished_period_rule() -> None:
    report = check_facts(["10 月新增订阅 1200 人。"], as_of="2026-10")
    assert any(f["rule"] == "unfinished_period_needs_to_date" for f in report["failures"])
    report = check_facts(["截至 10 月 20 日，10 月新增订阅 1200 人。"], as_of="2026-10")
    assert report["verdict"] == "pass"
    report = check_facts(["9 月新增订阅 1200 人。"], as_of="2026-10")
    assert report["verdict"] == "pass"
    report = check_facts(["Q4 to date 增长 5%。"], as_of="2026-10")
    assert report["verdict"] == "pass"


def test_facts_timing_not_cause_rule() -> None:
    report = check_facts(["HN spike 带来了 4705 名新订阅。"], as_of="2026-10")
    assert any(f["rule"] == "timing_not_cause" for f in report["failures"])
    report = check_facts(["HN spike 之后，订阅达到 4705 名。"], as_of="2026-10")
    assert report["verdict"] == "pass"
    report = check_facts(["数据显示 HN spike 导致订阅增长。"], as_of="2026-10")
    assert report["verdict"] == "pass"


def test_facts_number_needs_source_or_illustrative_warns() -> None:
    report = check_facts([], [{"text": "订阅 4705 名", "source": None}])
    assert report["verdict"] == "pass"
    assert report["warning_count"] == 1
    report = check_facts([], [{"text": "订阅 4705 名", "source": "subscribers.csv"}])
    assert report["warning_count"] == 0
    report = check_facts([], [{"text": "示意：订阅 4705 名", "source": None}])
    assert report["warning_count"] == 0


def test_new_capabilities_registered() -> None:
    from hevi.capabilities.registry import get

    for name in ("qa.timeline_gate", "qa.rendered_text_measure",
                 "qa.critic_review", "qa.facts_discipline"):
        assert get(name).name == name
