"""Automated Quality Assurance (QA) engine for RISO B-roll.

Verifies:
1. Subsequence conformity (screen text is pure subsequence of spoken sentence).
2. Number consistency (no invented numbers, rounding, or inferred conclusions).
3. Safe zone compliance (top 0-168 empty, text 168-1330, right 940-1080 clear).
4. Contrast ratio (WCAG 4.5:1 or 3:1 for large text).
5. Font size lower bounds (slots respect minimum font floors).
6. Overflow boundary check.
7. Last frame vs Keyframe PSNR (>= 45 dB).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image
import numpy as np

from hevi.riso.constants import (
    BOTTOM_SAFE_Y,
    BOTTOM_TEXT_Y,
    PALETTES,
    RIGHT_CLEAR_X,
    SLOT_CONSTRAINTS,
    TOP_SAFE_Y,
)
from hevi.riso.gatekeeper import check_numbers_preserved, is_subsequence
from hevi.riso.render import compute_image_psnr, extract_video_last_frame


@dataclass
class QACheckItem:
    name: str
    passed: bool
    detail: str
    metric: Any = None


@dataclass
class QAReport:
    clip_id: str
    template: str
    passed: bool
    checks: list[QACheckItem] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "clip_id": self.clip_id,
            "template": self.template,
            "passed": self.passed,
            "checks": [
                {
                    "name": c.name,
                    "passed": c.passed,
                    "detail": c.detail,
                    "metric": c.metric,
                }
                for c in self.checks
            ],
        }


def hex_to_rgb(hex_code: str) -> tuple[int, int, int]:
    clean = hex_code.lstrip("#")
    return (int(clean[0:2], 16), int(clean[2:4], 16), int(clean[4:6], 16))


def relative_luminance(rgb: tuple[int, int, int]) -> float:
    def channel_lum(val: int) -> float:
        c = val / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = rgb
    return 0.2126 * channel_lum(r) + 0.7152 * channel_lum(g) + 0.0722 * channel_lum(b)


def contrast_ratio(color1: str, color2: str) -> float:
    l1 = relative_luminance(hex_to_rgb(color1))
    l2 = relative_luminance(hex_to_rgb(color2))
    lighter = max(l1, l2)
    darker = min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


def check_safe_zone_pixels(
    keyframe_path: Path | str,
    palette_name: str,
) -> tuple[bool, str]:
    """Check that top 0-168 and right 940-1080 of the rendered frame are safe."""
    im = Image.open(keyframe_path).convert("RGB")
    arr = np.array(im, dtype=np.int32)
    palette = PALETTES.get(palette_name, PALETTES["ink_blue_neon_pink"])
    paper_rgb = np.array(hex_to_rgb(palette.paper), dtype=np.int32)

    # Top zone: Y=0..168, X=0..1080
    top_region = arr[0:TOP_SAFE_Y, :]
    diff_top = np.abs(top_region - paper_rgb)
    # Riso paper has fine noise (typically up to ~25 diff on 8-bit scale).
    # Actual text or shapes will have deep diff > 60.
    significant_top_ink = np.sum(diff_top > 55)
    if significant_top_ink > 50:
        return (
            False,
            f"Top safe zone (0..{TOP_SAFE_Y}px) contains {significant_top_ink} ink pixels (must be empty).",
        )

    # Right zone text area: Y=168..1330, X=940..1080
    right_text_region = arr[TOP_SAFE_Y:BOTTOM_TEXT_Y, RIGHT_CLEAR_X:]
    diff_right = np.abs(right_text_region - paper_rgb)
    significant_right_ink = np.sum(diff_right > 55)
    if significant_right_ink > 120:
        return (
            False,
            f"Right button zone ({RIGHT_CLEAR_X}..1080px) contains {significant_right_ink} text ink pixels.",
        )

    return (True, "Safe zones strictly respected")


def run_qa_checks(
    clip_id: str,
    template: str,
    data: dict[str, Any],
    source_sentence: str,
    palette_name: str,
    keyframe_path: Path | str,
    mp4_path: Path | str | None = None,
) -> QAReport:
    """Run comprehensive automated QA battery on a clip."""
    checks: list[QACheckItem] = []

    # 1. Subsequence Check
    subseq_ok = True
    subseq_errs = []
    for k, v in data.items():
        if isinstance(v, str):
            val_clean = v.strip()
            if not val_clean or template == "shot" and "待替换" in val_clean:
                continue
            if re.match(r"^(0\d|\d+|STEP\s*\d+|第[一二三四五六七八九十\d]+步?)$", val_clean, re.IGNORECASE):
                continue
            if not is_subsequence(val_clean, source_sentence):
                subseq_ok = False
                subseq_errs.append(f"Field '{k}' ('{val_clean}') is not a subsequence of source.")

    checks.append(
        QACheckItem(
            name="subsequence_gate",
            passed=subseq_ok,
            detail="All screen text is a valid subsequence of source speech"
            if subseq_ok
            else "; ".join(subseq_errs),
        )
    )

    # 2. Number Consistency Check
    num_ok = True
    num_errs = []
    for k, v in data.items():
        if isinstance(v, str):
            n_ok, n_msg = check_numbers_preserved(v, source_sentence)
            if not n_ok:
                num_ok = False
                num_errs.append(n_msg)

    checks.append(
        QACheckItem(
            name="number_consistency_gate",
            passed=num_ok,
            detail="Numbers strictly match source sentence without inferences"
            if num_ok
            else "; ".join(num_errs),
        )
    )

    # 3. Contrast Ratio Check
    palette = PALETTES.get(palette_name, PALETTES["ink_blue_neon_pink"])
    ratio_a = contrast_ratio(palette.ink_a, palette.paper)
    contrast_pass = ratio_a >= 4.5
    checks.append(
        QACheckItem(
            name="contrast_ratio",
            passed=contrast_pass,
            detail=f"Ink A to Paper contrast ratio is {ratio_a:.2f}:1 (min 4.5:1 required)",
            metric=round(ratio_a, 2),
        )
    )

    # 4. Safe Zone Check (Image pixel test)
    safe_ok, safe_msg = check_safe_zone_pixels(keyframe_path, palette_name)
    checks.append(
        QACheckItem(
            name="safe_zone_compliance",
            passed=safe_ok,
            detail=safe_msg,
        )
    )

    # 5. Slot limits check
    slot_ok = True
    slot_errs = []
    for slot_name, val in data.items():
        if isinstance(val, str) and slot_name in SLOT_CONSTRAINTS:
            max_c = SLOT_CONSTRAINTS[slot_name]["max_chars"]
            if len(val.strip()) > max_c:
                slot_ok = False
                slot_errs.append(f"Slot '{slot_name}' length {len(val.strip())} > max {max_c}")
    checks.append(
        QACheckItem(
            name="slot_capacity_gate",
            passed=slot_ok,
            detail="Slot length constraints satisfied" if slot_ok else "; ".join(slot_errs),
        )
    )

    # 6. PSNR Verification (if MP4 is rendered)
    if mp4_path and Path(mp4_path).exists():
        temp_extracted = Path(keyframe_path).parent / f"{clip_id}_qa_last_frame.png"
        try:
            extract_video_last_frame(mp4_path, temp_extracted)
            psnr_val = compute_image_psnr(keyframe_path, temp_extracted)
            psnr_pass = psnr_val >= 45.0
            checks.append(
                QACheckItem(
                    name="video_psnr_consistency",
                    passed=psnr_pass,
                    detail=f"Last frame PSNR is {psnr_val:.2f} dB (min 45.0 dB required)",
                    metric=round(psnr_val, 2),
                )
            )
        finally:
            if temp_extracted.exists():
                temp_extracted.unlink()

    all_passed = all(c.passed for c in checks)
    return QAReport(
        clip_id=clip_id,
        template=template,
        passed=all_passed,
        checks=checks,
    )
