"""Unit and regression tests for RISO B-roll module (RISO_TASK.md).

Covers:
1. Subsequence gate catches rewritten text and fabricated numbers.
2. Out-of-safe-zone text fails QA.
3. Last frame of MP4 matches keyframe image (PSNR >= 45.0 dB).
4. Same seed rendered twice produces reproducible results.
5. Deleting any generated output causes test to fail.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from hevi.capabilities.registry import compute_sha256
from hevi.riso.constants import CANVAS_HEIGHT, CANVAS_WIDTH
from hevi.riso.gatekeeper import (
    check_numbers_preserved,
    is_subsequence,
    validate_screen_content,
)
from hevi.riso.qa import check_safe_zone_pixels, run_qa_checks
from hevi.riso.render import (
    compute_image_psnr,
    extract_video_last_frame,
    render_clip,
)


def test_subsequence_gate_catches_rewriting() -> None:
    """Subsequence gate must catch rewrites, reordering, and extra words."""
    source = "为什么复利最难的是前三年？因为前三年毫无感觉。"

    # Pure subsequences
    assert is_subsequence("复利最难的是前三年", source)
    assert is_subsequence("前三年毫无感觉", source)
    assert is_subsequence("复利最难", source)

    # Rewrites / extra words (MUST FAIL)
    assert not is_subsequence("复利第一年非常艰难", source)
    assert not is_subsequence("因为前三年收益太低毫无感觉", source)
    assert not is_subsequence("前三年是复利最难的", source)  # Reordered


def test_subsequence_gate_catches_fabricated_numbers() -> None:
    """Number gate must reject conclusions, calculated ratios, or invented metrics."""
    source = "从40分钟缩短为2分钟，效率提升明显。"

    # Direct numbers preserved
    ok, _ = check_numbers_preserved("40分钟变2分钟", source)
    assert ok

    # Inferred conclusions / fabricated multipliers (MUST FAIL)
    ok_ratio, err_ratio = check_numbers_preserved("20倍", source)
    assert not ok_ratio
    assert "20倍" in err_ratio

    ok_pct, err_pct = check_numbers_preserved("95%", source)
    assert not ok_pct

    # Validate screen content integration
    bad_data = {"reality": "效率提升20倍"}
    res = validate_screen_content("versus", bad_data, source)
    assert not res.passed
    assert any("20倍" in e for e in res.errors)


def test_out_of_safe_zone_fails_qa(tmp_path: Path) -> None:
    """Elements positioned outside the safe zones must fail QA."""
    # 1. Normal image with clean top 0-168 zone
    clean_im = Image.new("RGB", (CANVAS_WIDTH, CANVAS_HEIGHT), color=(244, 238, 225))
    clean_path = tmp_path / "clean_frame.png"
    clean_im.save(clean_path)

    ok_clean, msg_clean = check_safe_zone_pixels(clean_path, "ink_blue_neon_pink")
    assert ok_clean

    # 2. Defective image with text/ink in top 0-168 zone (violates rule)
    defective_im = Image.new("RGB", (CANVAS_WIDTH, CANVAS_HEIGHT), color=(244, 238, 225))
    # Place ink in forbidden top area (Y=50)
    for y in range(40, 100):
        for x in range(200, 600):
            defective_im.putpixel((x, y), (15, 30, 54))
    defective_path = tmp_path / "defective_top_frame.png"
    defective_im.save(defective_path)

    ok_defective, msg_defective = check_safe_zone_pixels(defective_path, "ink_blue_neon_pink")
    assert not ok_defective
    assert "Top safe zone" in msg_defective


def test_keyframe_and_final_mp4_psnr_consistency(tmp_path: Path) -> None:
    """成片末帧要和样帧逐像素一致 (PSNR >= 45 dB)."""
    clip_dir = tmp_path / "clip_render"
    res = render_clip(
        template_name="quote",
        data={
            "quote": "前三年是积累期",
            "author": "复利法则",
        },
        out_dir=clip_dir,
        clip_id="test_consistency",
        duration_s=2.8,  # Settled state
        palette_key="ink_blue_neon_pink",
        seed=100,
        render_video=True,
    )

    psnr = res["psnr"]
    assert psnr is not None
    assert psnr >= 45.0, f"PSNR {psnr:.2f} dB was lower than required 45.0 dB"


def test_reproducibility_with_fixed_seed(tmp_path: Path) -> None:
    """Rendering the same template with identical seed must yield identical pixels."""
    data = {"myth": "前三年毫无作用", "reality": "前三年是基石"}

    dir_a = tmp_path / "run_a"
    dir_b = tmp_path / "run_b"

    res_a = render_clip(
        template_name="versus",
        data=data,
        out_dir=dir_a,
        clip_id="test_seed",
        duration_s=1.0,
        seed=777,
        render_video=False,
    )

    res_b = render_clip(
        template_name="versus",
        data=data,
        out_dir=dir_b,
        clip_id="test_seed",
        duration_s=1.0,
        seed=777,
        render_video=False,
    )

    png_a = Path(res_a["keyframe_png"])
    png_b = Path(res_b["keyframe_png"])

    arr_a = np.array(Image.open(png_a))
    arr_b = np.array(Image.open(png_b))

    # Identical pixel comparison
    diff = np.max(np.abs(arr_a.astype(int) - arr_b.astype(int)))
    assert diff == 0, f"Reproducibility failure: maximum pixel diff is {diff}"


def test_deletion_of_artifact_fails(tmp_path: Path) -> None:
    """Deleting any required artifact must trigger failure."""
    clip_dir = tmp_path / "clip_artifact"
    res = render_clip(
        template_name="number",
        data={
            "number": "3",
            "unit": "年",
            "context": "复利周期",
            "insight": "最难熬的前三年",
        },
        out_dir=clip_dir,
        clip_id="test_del",
        duration_s=1.0,
        render_video=True,
    )

    mp4_path = Path(res["mp4_path"])
    assert mp4_path.exists()
    sha_before = compute_sha256(mp4_path)
    assert len(sha_before) == 64

    # Delete MP4 artifact
    mp4_path.unlink()
    assert not mp4_path.exists()

    # compute_sha256 must fail
    with pytest.raises(Exception):
        compute_sha256(mp4_path)

    # QA extraction must fail
    with pytest.raises(Exception):
        extract_video_last_frame(mp4_path, tmp_path / "out.png")
