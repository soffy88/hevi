"""Comparison-eval skeleton for the video-director P0 grafts.

This is a harness, not an effectiveness claim: it renders two
short sample films with ``video.code_render`` (A clean, B with a
single sampled flash frame, an unplanned cut and a 1.2s frozen
run), runs the timeline gate, the final-QC defect scan, the
rendered-text measurement and the facts discipline over both, and
writes a pass/fail comparison table as JSON to ``tmp_path``. The
only assertions are that the harness runs, film A passes, and
film B's planted defects are detected. No conclusion about the
grafts improving films in general is drawn from n=1 sample films.
"""

from __future__ import annotations

import glob
import json
import shutil
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

from hevi.capabilities.code_render import assemble_mp4, render_frames
from hevi.capabilities.facts_discipline import check_facts
from hevi.capabilities.final_qc import run_final_qc
from hevi.capabilities.otsu_text import measure_rendered_text
from hevi.capabilities.timeline_gate import check_timeline

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe required",
)

DURATION = 5.0
TIER = "draft_720p30"  # 1280x720, 30fps


def _frame_fn(defective: bool):
    def frame_fn(t: float, i: int, width: int, height: int) -> Image.Image:
        xs = np.arange(width, dtype=np.float64)
        ys = np.arange(height, dtype=np.float64)[:, None]
        # Scene colour shifts at the planned cut (2.0s); film B adds
        # an unplanned shift at 3.0s.
        shift = 0.0
        if t >= 2.0:
            shift = 70.0
        if defective and t >= 3.0:
            shift = 140.0
        grey = np.clip(xs[None, :] * 0.09 + ys * 0.05 + shift, 0, 200)
        if defective and 3.5 <= t < 4.7:
            # Frozen run: identical content, pinned to the 3.5s phase.
            grey = np.clip(xs[None, :] * 0.09 + ys * 0.05 + 140.0, 0, 200)
            bar_x = (105 * 3) % (width - 60)
        else:
            bar_x = (i * 6) % (width - 60)
        grey = grey.copy()
        grey[:, bar_x:bar_x + 60] = np.clip(grey[:, bar_x:bar_x + 60] + 50, 0, 255)
        rgb = np.stack([grey, np.clip(grey * 0.8 + 20, 0, 255),
                        np.clip(grey * 0.6 + 40, 0, 255)], axis=2)
        img = Image.fromarray(rgb.astype(np.uint8), mode="RGB")
        if defective and 1.0 <= t < 1.134:
            # One sampled flash frame (the 7.5fps sample at 1.067s).
            img = Image.new("RGB", (width, height), (255, 255, 255))
        return img

    return frame_fn


def _timeline() -> dict:
    return {
        "meta": {"w": 1280, "h": 720, "fps": 30, "dur": DURATION,
                 "clock": "reads"},
        "scenes": [{"start": 0.0, "end": 2.0}, {"start": 2.0, "end": 5.0}],
        "beats": [0.0, 2.0, 4.0],
        "cuts": [2.0],
        "texts": [
            {"role": "hook", "text": "Why the sky is blue", "start": 0.0,
             "end": 2.0, "px": 64},
        ],
        "terms": [{"term": "scattering", "said": True, "shown": True}],
        "vo_words": [{"t": 0.4}, {"t": 0.9}, {"t": 1.4}],
        "captions": [{"start": 0.0, "end": 1.5, "words": 4}],
        "hero": {"t": 3.0},
        "silences": [{"start": 0.0, "end": 0.5}],
    }


def _text_frame(tmp_path: Path) -> tuple[Path, list[int]]:
    candidates = glob.glob("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
    if not candidates:
        pytest.skip("DejaVu font not available")
    img = Image.new("RGB", (1280, 720), "white")
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(candidates[0], 100)
    bbox = draw.textbbox((40, 200), "HELLO", font=font)
    draw.text((40, 200), "HELLO", font=font, fill=(0, 0, 0))
    path = tmp_path / "otsu_frame.png"
    img.save(path)
    return path, list(bbox)


def test_video_director_eval_skeleton(tmp_path: Path) -> None:
    results: dict[str, dict] = {}

    for label, defective in (("A_clean", False), ("B_defective", True)):
        frames_dir = tmp_path / f"{label}_frames"
        manifest = render_frames(_frame_fn(defective), TIER, DURATION, frames_dir)
        assert manifest["frame_count"] == 150
        assembly = assemble_mp4(frames_dir, 30, tmp_path / f"{label}.mp4")
        media = Path(assembly["mp4"])
        timeline = check_timeline(_timeline())
        qc = run_final_qc(
            media, defect_scan=True, planned_cuts=[2.0],
            expected_duration_sec=DURATION, expected_width=1280,
            expected_height=720, expected_codec="h264",
            subtitle_text="clean captions", work_dir=tmp_path / f"{label}_qc",
        )
        results[label] = {
            "timeline_verdict": timeline["verdict"],
            "timeline_errors": timeline["errors"],
            "qc_verdict": qc["verdict"],
            "defect_flash_pass": qc["checks"]["defect_flash"]["pass"],
            "defect_cuts_pass": qc["checks"]["defect_unplanned_cuts"]["pass"],
            "defect_scan_status": qc["defect_scan"]["status"],
            "flash_events": qc["defect_scan"]["flash"],
            "cuts_detected": qc["defect_scan"]["cuts_detected"],
            "unplanned_cuts": qc["defect_scan"]["unplanned_cuts"],
            "frozen_events": qc["defect_scan"]["frozen"],
            "defect_warnings": qc["defect_scan"]["warnings"],
        }

    frame_path, bbox = _text_frame(tmp_path)
    otsu = measure_rendered_text(frame_path, bbox, "hook", at_sec=0.0)
    facts_clean = check_facts(
        ["订阅达到 4705 名。"], [{"text": "订阅 4705 名", "source": "subscribers.csv"}],
        as_of="2026-10",
    )
    facts_bad = check_facts(
        ["计数器上升，显示 4705 名订阅者。", "HN spike 带来了 4705 名新订阅。"],
        as_of="2026-10",
    )
    table = {
        "films": results,
        "otsu": {
            "status": otsu["status"], "font_px": otsu["font_px"],
            "contrast_ratio": otsu["contrast_ratio"],
        },
        "facts_clean": {"verdict": facts_clean["verdict"],
                        "failures": facts_clean["failures"]},
        "facts_bad": {"verdict": facts_bad["verdict"],
                      "failures": facts_bad["failures"]},
    }
    out_path = tmp_path / "video_director_eval.json"
    out_path.write_text(json.dumps(table, ensure_ascii=False, indent=2), encoding="utf-8")

    # Skeleton assertions only: A passes, B's defects are detected.
    assert results["A_clean"]["timeline_verdict"] == "pass"
    assert results["A_clean"]["qc_verdict"] == "pass"
    assert results["A_clean"]["defect_scan_status"] == "pass"
    assert results["B_defective"]["defect_flash_pass"] is False
    assert results["B_defective"]["flash_events"], "B flash must be listed"
    assert results["B_defective"]["defect_cuts_pass"] is False
    assert results["B_defective"]["unplanned_cuts"], "B unplanned cut must be listed"
    assert results["B_defective"]["frozen_events"], "B frozen run must be listed"
    assert otsu["status"] == "pass"
    assert facts_clean["verdict"] == "pass"
    assert facts_bad["verdict"] == "fail"
