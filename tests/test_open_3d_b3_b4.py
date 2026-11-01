"""Tests for the open-3d-skills B3/B4 graft (clean-room, method only).

B3 scroll-film engine and B4 per-frame plate keyer. Real runs are
guarded on cv2/ffmpeg availability; pure plan checks always run.
No author-reported number appears as a threshold anywhere: every
seam/loop threshold is supplied by the test itself, and the
keyer similarity/blend defaults are hevi-chosen values recorded
in the module docstring.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from hevi.capabilities import get as _get_capability
from hevi.capabilities.alpha_cutout_keyer import (
    build_test_plate_frames,
    estimate_plate_color,
    key_frame,
    key_video,
)
from hevi.capabilities.chroma_key_gate import check_chroma_key_evidence
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.scroll_film_engine import (
    build_test_frames,
    check_scroll_plan,
    measure_seam,
    render_scroll_film,
)

try:
    import cv2  # noqa: F401
    import numpy as np  # noqa: F401

    CV2_OK = True
except ImportError:
    CV2_OK = False

FFMPEG_OK = shutil.which("ffmpeg") is not None
RUN_OK = CV2_OK and FFMPEG_OK

THRESHOLDS = {
    "seam_invisible_max": 0.01,
    "seam_jump_min": 0.05,
    "loop_jump_max": 0.01,
}


def _plan(legs, **overrides):
    total = sum(len(leg["frames"]) for leg in legs)
    plan = {
        "legs": legs,
        "keys": [[0.0, 0], [1.0, total - 1]],
        "smooth": 0.0,
        "output_frames": total,
        "fps": 10,
        "gop": 4,
        "delivery": "frames",
        "thresholds": dict(THRESHOLDS),
        "synthetic_source": True,
    }
    plan.update(overrides)
    return plan


# ---- B3 plan validation (always runs) ----


def test_b3_plan_rejects_empty_legs():
    report = check_scroll_plan({"legs": [], "keys": [[0.0, 0], [1.0, 0]]})
    assert report["verdict"] == "fail"
    assert any(i["code"] == "legs_missing" for i in report["issues"])


def test_b3_plan_rejects_non_four_gop():
    legs = [{"id": "a", "frames": ["f0.png", "f1.png"]}]
    report = check_scroll_plan(_plan(legs, gop=12))
    assert report["verdict"] == "fail"
    assert any(i["code"] == "gop_must_be_four" for i in report["issues"])


def test_b3_plan_requires_range_server_for_scrub_video():
    legs = [{"id": "a", "frames": ["f0.png", "f1.png"]}]
    report = check_scroll_plan(_plan(legs, delivery="scrub_video"))
    assert report["verdict"] == "fail"
    assert any(i["code"] == "range_server_required" for i in report["issues"])
    report = check_scroll_plan(
        _plan(legs, delivery="scrub_video", range_server=True)
    )
    assert report["verdict"] == "pass"


def test_b3_plan_rejects_decreasing_keys():
    legs = [{"id": "a", "frames": ["f0.png", "f1.png", "f2.png"]}]
    plan = _plan(legs, keys=[[0.0, 0], [0.5, 2], [0.4, 1], [1.0, 2]])
    report = check_scroll_plan(plan)
    assert report["verdict"] == "fail"
    assert any(i["code"] == "keys_not_monotonic" for i in report["issues"])


def test_b3_plan_rejects_missing_thresholds():
    legs = [{"id": "a", "frames": ["f0.png", "f1.png"]}]
    plan = _plan(legs)
    del plan["thresholds"]
    report = check_scroll_plan(plan)
    assert report["verdict"] == "fail"
    assert any(i["code"] == "thresholds_missing" for i in report["issues"])


def test_b3_plan_malformed_raises():
    with pytest.raises(CapabilityError):
        check_scroll_plan(["not", "a", "dict"])


# ---- B3 seam scoring and rendering ----


@pytest.mark.skipif(not CV2_OK, reason="cv2 unavailable")
def test_b3_seam_identical_is_zero_and_cut_is_visible():
    import numpy as np

    a = np.zeros((8, 8, 3), dtype=np.uint8)
    b = np.full((8, 8, 3), 255, dtype=np.uint8)
    assert measure_seam(a, a) == 0.0
    assert measure_seam(a, b) == 1.0
    with pytest.raises(CapabilityError):
        measure_seam(a, np.zeros((4, 4, 3), dtype=np.uint8))


@pytest.mark.skipif(not RUN_OK, reason="cv2/ffmpeg unavailable")
def test_b3_render_continuous_film_passes_gate(tmp_path):
    fixture = build_test_frames(tmp_path / "src")
    plan = _plan(fixture["legs"])
    out = tmp_path / "out"
    report = render_scroll_film(plan, out)
    assert report["rendered"] is True
    assert report["verdict"] == "pass", json.dumps(report["gate"], indent=2)
    assert (out / "scroll_film.mp4").exists()
    assert len(report["frame_hashes"]) == report["frame_count"]
    assert all(s["score"] == 0.0 for s in report["seam_scores"])
    assert len(report["seam_scores"]) == 2  # two leg boundaries


@pytest.mark.skipif(not RUN_OK, reason="cv2/ffmpeg unavailable")
def test_b3_render_cut_film_fails_gate(tmp_path):
    fixture = build_test_frames(tmp_path / "src", boundary_cut=True)
    plan = _plan(fixture["legs"])
    report = render_scroll_film(plan, tmp_path / "out")
    assert report["rendered"] is True
    assert report["verdict"] == "fail"
    # The restart cut scores in the visible band for a small moving
    # disc (whole-frame mean difference); the gate fails it, which
    # is the behaviour under test -- the scorer sees the jump.
    assert any(
        s["score"] > THRESHOLDS["seam_invisible_max"] for s in report["seam_scores"]
    )


@pytest.mark.skipif(not RUN_OK, reason="cv2/ffmpeg unavailable")
def test_b3_hold_key_holds_frame(tmp_path):
    fixture = build_test_frames(tmp_path / "src")
    total = sum(len(leg["frames"]) for leg in fixture["legs"])
    plan = _plan(
        fixture["legs"],
        keys=[[0.0, 0], [0.5, 0], [1.0, total - 1]],
        output_frames=total,
    )
    report = render_scroll_film(plan, tmp_path / "out")
    assert report["rendered"] is True
    # First half of the output holds source frame 0.
    assert len(set(report["source_positions"][: total // 2])) == 1


@pytest.mark.skipif(not RUN_OK, reason="cv2/ffmpeg unavailable")
def test_b3_two_renders_hash_identical(tmp_path):
    fixture = build_test_frames(tmp_path / "src")
    plan = _plan(fixture["legs"])
    first = render_scroll_film(plan, tmp_path / "run1")
    second = render_scroll_film(plan, tmp_path / "run2")
    assert first["frame_hashes"] == second["frame_hashes"]
    assert first["verdict"] == second["verdict"] == "pass"


@pytest.mark.skipif(not RUN_OK, reason="cv2/ffmpeg unavailable")
def test_b3_render_missing_frame_raises(tmp_path):
    fixture = build_test_frames(tmp_path / "src")
    legs = [
        {"id": "a", "frames": fixture["legs"][0]["frames"]},
        {"id": "b", "frames": [str(tmp_path / "nope.png")]},
    ]
    with pytest.raises(CapabilityError):
        render_scroll_film(_plan(legs), tmp_path / "out")


@pytest.mark.skipif(not RUN_OK, reason="cv2/ffmpeg unavailable")
def test_b3_loop_film_judges_first_last_agreement(tmp_path):
    fixture = build_test_frames(tmp_path / "src")
    total = sum(len(leg["frames"]) for leg in fixture["legs"])
    plan = _plan(
        fixture["legs"],
        keys=[[0.0, 0], [0.5, total - 1], [1.0, 0]],
        loop=True,
    )
    report = render_scroll_film(plan, tmp_path / "out")
    assert report["rendered"] is True
    assert report["loop_judged"] is True
    assert report["loop_score"] == 0.0
    assert report["verdict"] == "pass"


def test_b3_capability_registered():
    cap = _get_capability("video.scroll_film_engine")
    assert cap.name == "video.scroll_film_engine"


# ---- B4 plate estimation and keying ----


@pytest.mark.skipif(not CV2_OK, reason="cv2 unavailable")
def test_b4_plate_estimate_recovers_drifting_plate(tmp_path):
    import numpy as np

    fixture = build_test_plate_frames(tmp_path / "src", n_frames=6)
    first = cv2.imread(fixture["frames"][0], cv2.IMREAD_COLOR)
    last = cv2.imread(fixture["frames"][-1], cv2.IMREAD_COLOR)
    first_plate = estimate_plate_color(first)
    last_plate = estimate_plate_color(last)
    # BGR: pure green (0,255,0) -> pale (170,255,140).
    assert abs(float(first_plate[1]) - 255.0) < 2.0
    assert float(last_plate[0]) > 100.0  # blue channel drifted up
    assert float(np.max(np.abs(first_plate - last_plate))) > 50.0


@pytest.mark.skipif(not CV2_OK, reason="cv2 unavailable")
def test_b4_fixed_plate_fails_on_drifted_frame_but_measured_holds(tmp_path):
    import numpy as np

    fixture = build_test_plate_frames(tmp_path / "src", n_frames=12)
    first = cv2.imread(fixture["frames"][0], cv2.IMREAD_COLOR)
    last = cv2.imread(fixture["frames"][-1], cv2.IMREAD_COLOR)
    fixed_plate = estimate_plate_color(first)
    fixed = key_frame(last, plate_color=fixed_plate)
    measured = key_frame(last)
    # The fixed colour leaves the drifted plate partly opaque;
    # per-frame measurement keys it out. Compare mean alpha over
    # the border ring (plate-only region) of the last frame.
    ring_fixed = fixed["alpha"][:4, :].mean()
    ring_measured = measured["alpha"][:4, :].mean()
    assert ring_fixed > 0.2
    assert ring_measured < 0.05
    assert np.mean(np.abs(fixed["alpha"] - measured["alpha"])) > 0.05


@pytest.mark.skipif(not CV2_OK, reason="cv2 unavailable")
def test_b4_subject_touching_border_fails_loudly():
    import numpy as np

    frame = np.zeros((40, 40, 3), dtype=np.uint8)
    frame[:, :] = (0, 255, 0)
    frame[0:8, 0:8] = (0, 0, 255)  # subject in the border ring
    with pytest.raises(CapabilityError):
        estimate_plate_color(frame)


@pytest.mark.skipif(not RUN_OK, reason="cv2/ffmpeg unavailable")
def test_b4_key_video_delivers_and_gate_passes(tmp_path):
    fixture = build_test_plate_frames(tmp_path / "src", n_frames=12)
    job = {
        "frames_dir": fixture["frames_dir"],
        "fps": 12,
        "deliveries": ["stacked_alpha", "vp9_alpha", "webp"],
        "ground_y_px": 168,
        "designed_height_ratio": 0.30,
        "stage_light_angle_deg": 45.0,
        "stage_light_intensity": 1.0,
        "synthetic_source": True,
    }
    report = key_video(job, tmp_path / "out")
    assert report["verdict"] == "pass", json.dumps(report["gate"], indent=2)
    assert (tmp_path / "out" / "stacked_alpha.mp4").exists()
    assert len(report["deliveries"]["webp"]["frames"]) == 12
    assert report["deliveries"]["vp9_alpha"]["safari_supported"] is False
    assert report["deliveries"]["stacked_alpha"]["safari_supported"] is True
    assert len(report["check_frames"]) == 9  # 3 backgrounds x 3 frames


@pytest.mark.skipif(not RUN_OK, reason="cv2/ffmpeg unavailable")
def test_b4_vp9_alpha_availability_is_verified_not_assumed(tmp_path):
    fixture = build_test_plate_frames(tmp_path / "src", n_frames=4)
    job = {
        "frames_dir": fixture["frames_dir"],
        "fps": 12,
        "deliveries": ["vp9_alpha"],
        "ground_y_px": 168,
        "designed_height_ratio": 0.30,
        "stage_light_angle_deg": 45.0,
        "stage_light_intensity": 1.0,
        "synthetic_source": True,
    }
    report = key_video(job, tmp_path / "out")
    vp9 = report["deliveries"]["vp9_alpha"]
    if vp9["available"]:
        probe = subprocess.run(
            [
                "ffprobe", "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=pix_fmt,codec_name",
                "-of", "csv=p=0",
                vp9["path"],
            ],
            capture_output=True, text=True,
        )
        assert "vp9" in probe.stdout
        assert "yuva420p" in probe.stdout
    else:
        # This environment's ffmpeg/libvpx drops the alpha plane:
        # the unavailability must be recorded with the observed
        # pixel format, and no file may be claimed.
        assert vp9["path"] is None
        assert "yuva420p" in vp9["reason"]
        assert not (tmp_path / "out" / "alpha_vp9.webm").exists()


@pytest.mark.skipif(not RUN_OK, reason="cv2/ffmpeg unavailable")
def test_b4_webp_frames_carry_alpha(tmp_path):
    from PIL import Image

    fixture = build_test_plate_frames(tmp_path / "src", n_frames=4)
    job = {
        "frames_dir": fixture["frames_dir"],
        "fps": 12,
        "deliveries": ["webp"],
        "ground_y_px": 168,
        "designed_height_ratio": 0.30,
        "stage_light_angle_deg": 45.0,
        "stage_light_intensity": 1.0,
        "synthetic_source": True,
    }
    report = key_video(job, tmp_path / "out")
    first = Image.open(report["deliveries"]["webp"]["frames"][0])
    assert first.mode == "RGBA"
    assert first.getchannel("A").getextrema()[0] == 0  # plate is transparent


@pytest.mark.skipif(not RUN_OK, reason="cv2/ffmpeg unavailable")
def test_b4_empty_frames_dir_raises(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(CapabilityError):
        key_video(
            {
                "frames_dir": str(empty),
                "ground_y_px": 168,
                "designed_height_ratio": 0.30,
                "stage_light_angle_deg": 45.0,
                "stage_light_intensity": 1.0,
            },
            tmp_path / "out",
        )


def test_b4_capability_registered():
    cap = _get_capability("video.alpha_cutout_keyer")
    assert cap.name == "video.alpha_cutout_keyer"
