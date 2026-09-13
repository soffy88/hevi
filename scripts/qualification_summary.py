#!/usr/bin/env python3
"""Render the machine-readable line qualification summary as Markdown."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path("artifacts/qualification/summary.json"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/qualification/summary.md"))
    args = parser.parse_args()
    summary = json.loads(args.input.read_text(encoding="utf-8"))
    lines = ["# HEVI line qualification summary", "", f"Total: {summary['total']}", "", "| Line | Status | Complete | Real E2E | Quality gate | Provider | Artifact | Blockers |", "|---|---|---:|---|---|---|---|---|"]
    for item in summary["lines"]:
        blockers = "; ".join(item["blockers"]) or "—"
        provider = ", ".join(item.get("provider", [])) or "—"
        lines.append(f"| {item['line']} | {item['status']} | {item['completeness_percent']}% | {item['real_e2e']} | {item['quality_gate']} | {provider} | {item['final_artifact']} | {blockers} |")
    lines.extend(["", "## Counts", ""])
    for status, count in summary["counts"].items():
        lines.append(f"- {status}: {count}")
    args.output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
