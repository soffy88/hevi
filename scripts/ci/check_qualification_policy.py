#!/usr/bin/env python3
"""Enforce release policy for the generated qualification summary."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    path = Path("artifacts/qualification/summary.json")
    if not path.exists():
        print("qualification summary missing; run scripts/qualify_lines.py", file=sys.stderr)
        return 1
    summary = json.loads(path.read_text(encoding="utf-8"))
    counts = summary.get("counts", {})
    if counts.get("FAILED", 0) or counts.get("PARTIAL", 0):
        print("qualification policy failed: FAILED/PARTIAL lines are not releasable", file=sys.stderr)
        return 1
    for item in summary.get("lines", []):
        if item["status"] == "PRODUCTION_COMPLETE":
            required = ("recipe_complete", "runtime_complete", "provider_available", "real_e2e", "final_artifact", "ffprobe_valid", "media_quality", "provenance_complete", "retry_verified", "observability_complete", "security_gate")
            if not all(item.get(field) for field in required):
                print(f"invalid PRODUCTION_COMPLETE report: {item['line']}", file=sys.stderr)
                return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
