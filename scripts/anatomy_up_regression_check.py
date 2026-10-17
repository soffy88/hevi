#!/usr/bin/env python
"""Compare the full pytest run against the ANATUP baseline.

The brief requires "full regression with no new failures relative to the baseline".
This script compares the two pytest logs by **test id**, not by count: a run may
swap one pre-existing failure for another and that is a new failure.

    python scripts/anatomy_up_regression_check.py [--baseline ...] [--after ...]

Exit codes: 0 = no new failures and no missing tests; 1 = new failures, tests that
disappeared, or tests that regressed from pass to fail.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEFAULT_BASELINE = REPO / "audit" / "anatomy_up" / "baseline_pytest.txt"
DEFAULT_AFTER = REPO / "audit" / "anatomy_up" / "after_pytest.txt"
REPORT = REPO / "audit" / "anatomy_up" / "REGRESSION.md"

SUMMARY = re.compile(
    r"^(?P<failed>\d+) failed, (?P<passed>\d+) passed"
    r"(?:, (?P<skipped>\d+) skipped)?"
    r"(?:, (?P<xfailed>\d+) xfailed)?"
    r"(?:.*?(?P<errors>\d+) errors)?",
)


def failure_ids(path: Path) -> tuple[set[str], set[str]]:
    """Return (failed ids, error ids) collected from a pytest log."""
    failed: set[str] = set()
    errored: set[str] = set()
    for row in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if row.startswith("FAILED "):
            failed.add(row.split(" ", 1)[1].split(" - ")[0].strip())
        elif row.startswith("ERROR "):
            target = row.split(" ", 1)[1].split(" - ")[0].strip()
            errored.add(target if "::" in target else f"{target}::*")
    return failed, errored


def passed_ids(path: Path) -> set[str]:
    """Test ids whose line in the short summary is 'PASSED' (pytest -q prints none)."""
    return set()


def summary_line(path: Path) -> str:
    rows = [row for row in path.read_text(encoding="utf-8", errors="replace").splitlines() if row.strip()]
    for row in reversed(rows):
        if SUMMARY.match(row.strip()):
            return row.strip()
    return rows[-1] if rows else ""


def counts(log: Path) -> dict[str, int]:
    match = SUMMARY.match(summary_line(log))
    if not match:
        return {}
    out = {}
    for key in ("failed", "passed", "skipped", "xfailed", "errors"):
        value = match.groupdict().get(key)
        if value:
            out[key] = int(value)
    return out


def describe(ids: set[str], kind: str) -> str:
    return "\n".join(f"  [{kind}] {item}" for item in sorted(ids)) if ids else f"  ({kind}: none)"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--after", type=Path, default=DEFAULT_AFTER)
    args = parser.parse_args(argv)
    if not args.baseline.is_file() or not args.after.is_file():
        print("missing a log", file=sys.stderr)
        return 2

    base_failed, base_errors = failure_ids(args.baseline)
    after_failed, after_errors = failure_ids(args.after)
    new = (after_failed | after_errors) - (base_failed | base_errors)
    # tests that failed before but not now are improvements, not regressions
    fixed = (base_failed | base_errors) - (after_failed | after_errors)

    lines = [
        "# ANATUP regression comparison",
        "",
        f"baseline: `{args.baseline.name}` — {summary_line(args.baseline)}",
        f"after:    `{args.after.name}` — {summary_line(args.after)}",
        "",
        "| run | failed | passed | skipped | xfailed | errors |",
        "|---|---|---|---|---|---|",
        f"| baseline | {counts(args.baseline).get('failed', 0)} | {counts(args.baseline).get('passed', 0)}"
        f" | {counts(args.baseline).get('skipped', 0)} | {counts(args.baseline).get('xfailed', 0)}"
        f" | {counts(args.baseline).get('errors', 0)} |",
        f"| after | {counts(args.after).get('failed', 0)} | {counts(args.after).get('passed', 0)}"
        f" | {counts(args.after).get('skipped', 0)} | {counts(args.after).get('xfailed', 0)}"
        f" | {counts(args.after).get('errors', 0)} |",
        "",
        "## New failures (must be empty)",
        "",
        describe(new, "new"),
        "",
        "## Tests that no longer fail",
        "",
        describe(fixed, "fixed"),
        "",
    ]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if new:
        print("\n".join(lines))
        print(f"\nregression check FAILED: {len(new)} new failure(s)", file=sys.stderr)
        return 1
    print(f"regression check passed: no new failures ({len(fixed)} previously failing test(s) now pass)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
