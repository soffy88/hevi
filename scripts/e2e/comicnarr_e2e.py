#!/usr/bin/env python3
"""E2E Acceptance Runner for COMICNARR line (real neural models on CPU, zero mock).

Executes:
1. Topic input: "为什么猫总爱把东西推下桌？" with comic_color style (45-75s)
2. Classical story adaptation: "促织：古画里的秋声" (聊斋自编改编) with manga_bw style (45-75s)
3. Three Kingdoms story: "草船借箭" with guofeng_anime style (45-75s)

Generates full product directory with:
  final.mp4, frames/ (winner + loser candidates), script.json, record.json, qa.json, contact_sheet.jpg, subtitles.srt.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

# Add project root to sys.path
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from hevi.layer4_legacy.comicnarr.omodul_impl.comicnarr_pipeline import (
    comic_narration_workflow,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("comicnarr_e2e")


def run_story(
    *,
    name: str,
    topic: str,
    style: str,
    output_dir: Path,
    base_seed: int,
    engine: str = "sdturbo_cpu",
    tts_engine: str = "piper",
    subtitle_style: str = "bottom",
) -> dict:
    logger.info("=" * 60)
    logger.info("Starting E2E Story: '%s'", name)
    logger.info("Topic: '%s'", topic)
    logger.info("Style: '%s' | Engine: '%s' | Output: %s", style, engine, output_dir)
    logger.info("=" * 60)

    t0 = time.time()
    input_data = {
        "topic": topic,
        "style": style,
        "keyframe_engine": engine,
        "tts_engine": tts_engine,
        "subtitle_style": subtitle_style,
        "base_seed": base_seed,
        "width": 1080,
        "height": 1920,
        "fps": 25,
    }

    result = comic_narration_workflow({}, input_data, output_dir)
    elapsed = time.time() - t0

    qa = result.get("qa") or {}
    record = result.get("record") or {}

    logger.info("Completed '%s' in %.1fs with status: %s", name, elapsed, result.get("status"))
    logger.info(
        "Measured Video: %.2fs | %dx%d @ %.1ffps | QA Passed: %s",
        qa.get("video", {}).get("duration", 0),
        qa.get("video", {}).get("width", 0),
        qa.get("video", {}).get("height", 0),
        qa.get("video", {}).get("fps", 0),
        qa.get("passed", False),
    )
    logger.info(
        "Audio Mean Volume: %.1f dB | Motion Diff: %.2f | Distinct Keyframes: %s",
        qa.get("audio", {}).get("mean_volume_db", -99),
        qa.get("motion", {}).get("mean_within_shot_difference", 0),
        qa.get("all_keyframes_distinct", False),
    )

    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="COMICNARR E2E Real Acceptance Suite")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("output/comicnarr_e2e"),
        help="Root output directory",
    )
    parser.add_argument(
        "--engine",
        default="sdturbo_cpu",
        help="Keyframe engine (default: sdturbo_cpu)",
    )
    parser.add_argument(
        "--tts-engine",
        default="piper",
        help="TTS engine (default: piper)",
    )
    parser.add_argument(
        "--run-only",
        choices=["story1", "story2", "story3", "all"],
        default="all",
        help="Run specific story or all",
    )

    args = parser.parse_args()
    root_out = args.output
    root_out.mkdir(parents=True, exist_ok=True)

    results = []

    # Story 1: Modern topic (Cats knocking things off tables)
    if args.run_only in ("story1", "all"):
        res1 = run_story(
            name="Story 1: 猫咪推杯子 (comic_color)",
            topic="为什么猫总爱把东西推下桌？猫咪的重力实验与捕食本能探索",
            style="comic_color",
            output_dir=root_out / "story1_cat_knock",
            base_seed=42,
            engine=args.engine,
            tts_engine=args.tts_engine,
            subtitle_style="bottom",
        )
        results.append(("Story 1 (Cat Knock, comic_color)", res1))

    # Story 2: Classical Chinese story (Liaozhai adaptation: 促织)
    if args.run_only in ("story2", "all"):
        res2 = run_story(
            name="Story 2: 聊斋志异·促织 (manga_bw)",
            topic="聊斋志异名篇《促织》改编：书生成名寻促织，古画神符显通灵，蟋蟀勇斗解危机",
            style="manga_bw",
            output_dir=root_out / "story2_cuozhi_manga",
            base_seed=108,
            engine=args.engine,
            tts_engine=args.tts_engine,
            subtitle_style="bubble",
        )
        results.append(("Story 2 (Cuozhi Fable, manga_bw)", res2))

    # Story 3: Three Kingdoms (草船借箭) with the shared guofeng_anime preset
    if args.run_only in ("story3", "all"):
        res3 = run_story(
            name="Story 3: 三国·草船借箭 (guofeng_anime)",
            topic="三国演义·草船借箭：诸葛亮大雾之中向曹军借来十万支箭的智谋",
            style="guofeng_anime",
            output_dir=root_out / "story3_sanguo_guofeng",
            base_seed=2024,
            engine=args.engine,
            tts_engine=args.tts_engine,
            subtitle_style="bottom",
        )
        results.append(("Story 3 (Sanguo, guofeng_anime)", res3))

    # Summary table
    print("\n" + "=" * 80)
    print("COMICNARR E2E ACCEPTANCE SUMMARY REPORT")
    print("=" * 80)
    print(
        f"{'STORY':<35} | {'DUR(s)':<7} | {'RES':<10} | {'AUDIO(dB)':<10} | {'MOTION':<7} | {'OCR_MIN':<8} | {'GRAY':<5} | {'DISTINCT_KF':<11} | {'QA_PASS'}"
    )
    print("-" * 80)

    all_passed = True
    for label, res in results:
        qa = res.get("qa") or {}
        v = qa.get("video") or {}
        a = qa.get("audio") or {}
        m = qa.get("motion") or {}
        rd = qa.get("subtitle_readability") or {}
        gy = qa.get("grayscale") or {}
        dur = v.get("duration", 0)
        res_str = f"{v.get('width', 0)}x{v.get('height', 0)}"
        vol = a.get("mean_volume_db", -99)
        diff = m.get("mean_within_shot_difference", 0)
        ocr_min = rd.get("min_similarity", 0)
        gray = "YES" if gy.get("all_grayscale") else ("n/a" if not gy.get("required") else "NO")
        dist = "YES" if qa.get("all_keyframes_distinct") else "NO"
        p = "PASS" if qa.get("passed") else "FAIL"
        if not qa.get("passed"):
            all_passed = False

        print(
            f"{label:<35} | {dur:<7.1f} | {res_str:<10} | {vol:<10.1f} | {diff:<7.2f} | {ocr_min:<8.3f} | {gray:<5} | {dist:<11} | {p}"
        )

    print("=" * 80)

    if all_passed:
        logger.info("ALL E2E ACCEPTANCE TESTS PASSED!")
        return 0
    else:
        logger.error("SOME E2E ACCEPTANCE GATES FAILED!")
        return 1


if __name__ == "__main__":
    sys.exit(main())
