#!/usr/bin/env python3
"""Analyze a local video with HEVI's CPU-only Video Intelligence core."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from hevi.video_intelligence.analysis import analyze_reel, save_analysis
from hevi.video_intelligence.task_contract import preflight_video


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("video", type=Path)
    parser.add_argument("--output", type=Path, default=Path("artifacts/video_intelligence"))
    parser.add_argument("--shot-threshold", type=float, default=0.35)
    parser.add_argument("--rhythm", action="store_true")
    parser.add_argument("--transcript", type=Path)
    parser.add_argument("--semantic", action="store_true")
    parser.add_argument("--json", action="store_true", dest="json_output")
    args = parser.parse_args()
    preflight = preflight_video(args.video, output_dir=args.output)
    if preflight.status != "READY":
        blocked_payload = {"status": "BLOCKED", "errors": preflight.errors}
        print(json.dumps(blocked_payload, ensure_ascii=False) if args.json_output else blocked_payload)
        return 2
    try:
        analysis = analyze_reel(args.video, threshold=args.shot_threshold, semantic=args.semantic)
        save_analysis(analysis, args.output)
    except RuntimeError as exc:
        error_payload = {"status": "FAILED", "error": str(exc)}
        print(json.dumps(error_payload, ensure_ascii=False) if args.json_output else error_payload)
        return 1
    payload: dict[str, object] = {
        "status": "SUCCEEDED" if analysis.quality_report.status.value != "FAIL" else "FAILED",
        "analysis_id": analysis.analysis_id,
        "asset_id": analysis.video_asset.asset_id,
        "outputs": {
            "analysis": str(args.output / "analysis.json"),
            "shots": str(args.output / "shots.json"),
            "quality": str(args.output / "quality.json"),
            "provenance": str(args.output / "provenance.json"),
        },
        "metrics": analysis.statistics.model_dump(mode="json"),
        "errors": [item.message for item in analysis.quality_report.findings if item.status.value == "FAIL"],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2) if args.json_output else payload)
    return 0 if payload["status"] == "SUCCEEDED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
