#!/usr/bin/env python3
"""Run real end-to-end handdraw productions for landscape and portrait deliverables.

Generates:
1. Landscape (1920x1080): 「为什么越生气越容易做错决定」
   - Style: 8 (水墨写意), Hand: navy (深蓝袖马克笔手臂)
2. Portrait (1080x1920): 「复利效应」
   - Style: 1 (极简黑白线条), Hand: pen-only (仅画笔 · 无手臂)

Outputs: MP4, cover PNG, SRT, script txt, verification report with SHA-256, duration, LUFS.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from pathlib import Path

# Set PYTHONPATH
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from hevi.layer4_legacy.handdraw.line import STANDARD_TOPIC_STORYBOARDS
from hevi.layer4_legacy.handdraw.pipeline import render_handdraw_pipeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("handdraw_e2e")

FFPROBE = "/home/soffy/.local/bin/ffprobe"


def run_e2e_samples(output_base: Path) -> dict[str, Any]:
    output_base = output_base.resolve()
    output_base.mkdir(parents=True, exist_ok=True)

    results = {}

    # -----------------------------------------------------------------------
    # Sample 1: Landscape (1920x1080) - 为什么越生气越容易做错决定
    # -----------------------------------------------------------------------
    logger.info("=== Running E2E Sample 1: Landscape 1920x1080 (Anger Decisions) ===")
    out_landscape = output_base / "landscape_anger"
    spec_landscape = STANDARD_TOPIC_STORYBOARDS["anger_decision"]

    res_landscape = render_handdraw_pipeline(
        job_id="handdraw_landscape_anger",
        title=spec_landscape["title"],
        pages_spec=spec_landscape["pages"],
        output_dir=out_landscape,
        canvas_size=(1920, 1080),
        style_id="8",  # 水墨写意
        hand_preset="navy",  # 深蓝袖马克笔
        prefer_cosy=True,
    )
    results["landscape_anger"] = res_landscape
    logger.info("Sample 1 completed: %s", res_landscape)

    # -----------------------------------------------------------------------
    # Sample 2: Portrait (1080x1920) - 复利效应
    # -----------------------------------------------------------------------
    logger.info("=== Running E2E Sample 2: Portrait 1080x1920 (Compound Interest) ===")
    out_portrait = output_base / "portrait_compound"
    spec_portrait = STANDARD_TOPIC_STORYBOARDS["compound_interest"]

    res_portrait = render_handdraw_pipeline(
        job_id="handdraw_portrait_compound",
        title=spec_portrait["title"],
        pages_spec=spec_portrait["pages"],
        output_dir=out_portrait,
        canvas_size=(1080, 1920),
        style_id="1",  # 极简黑白线条
        hand_preset="pen-only",  # 仅画笔 · 无手臂
        prefer_cosy=True,
    )
    results["portrait_compound"] = res_portrait
    logger.info("Sample 2 completed: %s", res_portrait)

    summary_file = output_base / "e2e_summary.json"
    summary_file.write_text(json.dumps(results, ensure_ascii=False, indent=2))
    logger.info("All E2E samples completed! Summary written to %s", summary_file)
    return results


if __name__ == "__main__":
    out_dir = REPO_ROOT / "artifacts" / "handdraw"
    run_e2e_samples(out_dir)
