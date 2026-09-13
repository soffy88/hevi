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

from hevi.qualification.framework import discover_reports, write_reports


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
    args = parser.parse_args()
    if args.real:
        os.environ["HEVI_QUALIFICATION_REAL"] = "1"
    if args.preflight or args.provider_ready_only:
        subprocess.run([sys.executable, "scripts/provider_readiness.py"], check=False)
    if args.preflight:
        subprocess.run([sys.executable, "scripts/gpu_readiness.py"], check=False)
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
        existing = []
        for report in reports:
            path = args.output / report["line"] / "result.json"
            if path.exists():
                existing.append(json.loads(path.read_text(encoding="utf-8")))
            else:
                existing.append(report)
        reports = existing
    summary = write_reports(reports, args.output)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
