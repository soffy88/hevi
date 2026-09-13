#!/usr/bin/env python3
"""Discover every Studio line and emit evidence-first qualification reports.

This command never creates a fake artifact.  Set HEVI_QUALIFICATION_REAL=1 only
when the caller has configured real providers and supplies their evidence.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from hevi.qualification.framework import PRODUCTION_FIELDS, discover_reports, write_reports
from scripts.real_line_qualification import qualify_line


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lines-dir", type=Path, default=Path("hevi/studio/lines"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/qualification"))
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--line", dest="line_id")
    parser.add_argument("--provider-ready-only", action="store_true")
    parser.add_argument("--non-gpu-only", action="store_true")
    parser.add_argument("--gpu-only", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--real", action="store_true")
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--eligible-only", action="store_true")
    args = parser.parse_args()
    if args.real:
        os.environ["HEVI_QUALIFICATION_REAL"] = "1"
    if args.preflight or args.provider_ready_only:
        subprocess.run([sys.executable, "scripts/provider_readiness.py"], check=False)
    if args.preflight:
        subprocess.run([sys.executable, "scripts/gpu_readiness.py"], check=False)
        subprocess.run([sys.executable, "scripts/gpu_diagnostic.py"], check=False)
        subprocess.run([sys.executable, "scripts/media_source_diagnostic.py"], check=False)
        if args.provider_ready_only:
            return 0
    reports = discover_reports(args.lines_dir, args.output)
    if args.line_id:
        reports = [item for item in reports if item["line"] == args.line_id]
    if args.non_gpu_only:
        reports = [item for item in reports if "h3_local" not in item["provider_required"]]
    if args.gpu_only:
        reports = [item for item in reports if "h3_local" in item["provider_required"]]
    if args.resume:
        current_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        existing = []
        for report in reports:
            path = args.output / report["line"] / "result.json"
            if path.exists():
                prior = json.loads(path.read_text(encoding="utf-8"))
                if prior.get("evidence", {}).get("git_sha") != current_sha:
                    report["stale"] = True
                    report["stale_evidence"] = {"previous_git_sha": prior.get("evidence", {}).get("git_sha"), "current_git_sha": current_sha}
                    existing.append(report)
                else:
                    existing.append(prior)
            else:
                existing.append(report)
        reports = existing
    if args.real:
        priority = {name: index for index, name in enumerate(("kinetic_promo", "shorts_clip", "history_scene", "localization_dub", "explainer", "documentary_montage", "podcast_repurpose", "reference_adapt", "character_animation", "director_pipeline", "cinematic", "talking_head", "avatar_spokesperson"))}
        reports.sort(key=lambda item: priority.get(item["line"], 999))
        current_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        for index, report in enumerate(reports):
            if report.get("provider_available") and not report.get("real_e2e"):
                evidence = qualify_line(report["line"], args.output)
                if evidence is not None:
                    merged = {**report, **evidence}
                    merged.pop("stale", None)
                    merged.pop("stale_evidence", None)
                    merged["evidence"] = {**report.get("evidence", {}), **evidence.get("evidence", {}), "git_sha": current_sha}
                    merged["production_completeness"] = round(100 * sum(bool(merged[field]) for field in PRODUCTION_FIELDS) / len(PRODUCTION_FIELDS))
                    merged["completeness_percent"] = merged["production_completeness"]
                    reports[index] = merged
                elif not args.eligible_only:
                    report["blockers"].append("real_e2e_runner_unavailable_for_line")
    summary = write_reports(reports, args.output)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
