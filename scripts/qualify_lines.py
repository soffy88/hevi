#!/usr/bin/env python3
"""Discover every Studio line and emit evidence-first qualification reports.

This command never creates a fake artifact.  Set HEVI_QUALIFICATION_REAL=1 only
when the caller has configured real providers and supplies their evidence.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from hevi.qualification.framework import discover_reports, write_reports


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lines-dir", type=Path, default=Path("hevi/studio/lines"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/qualification"))
    args = parser.parse_args()
    reports = discover_reports(args.lines_dir, args.output)
    summary = write_reports(reports, args.output)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
