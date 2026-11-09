#!/usr/bin/env python3
"""Optional PR gate: validate the four probe JSON files and derive a verdict.

Method only, re-expressed from kyy-logs/code-review-skill (MIT): four probes
(behavior-review, test-coverage, repo-guard required; impact-analysis optional),
each finding carries location/summary/evidence/severity/status, and the gate is
computed from JSON, never from prose.  The upstream skill still needs an agent to
run the probes; this script only enforces their contract.

Method only, re-expressed from kyy-logs/code-review-skill (MIT).  The upstream
LICENSE and attribution are kept in CODE_REVIEW_SKILL_ATTRIBUTION.md.

Usage:
    python3 scripts/code_review_gate.py <review_dir>

<review_dir> layout (same as the upstream skill):
    review_dir/probes/behavior-review.json
    review_dir/probes/test-coverage.json
    review_dir/probes/repo-guard.json
    review_dir/probes/impact-analysis.json   # optional
Exit 0 = pass, 1 = block.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROBES = ("behavior-review", "test-coverage", "repo-guard")
OPTIONAL = ("impact-analysis",)
SEVERITIES = {"high", "medium", "low"}
STATUSES = {"open", "reconciled", "wontfix", "false-positive"}


def _validate_findings(probe: str, payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    findings = payload.get("findings", [])
    if not isinstance(findings, list):
        return [f"{probe}: findings must be a list"]
    for i, f in enumerate(findings):
        where = f"{probe}[{i}]"
        if not isinstance(f, dict):
            errors.append(f"{where}: finding must be an object")
            continue
        errors.extend(
            f"{where}: missing {key}"
            for key in ("location", "summary", "evidence")
            if not str(f.get(key, "")).strip()
        )
        if f.get("severity") not in SEVERITIES:
            errors.append(f"{where}: severity must be one of {sorted(SEVERITIES)}")
        if f.get("status") not in STATUSES:
            errors.append(f"{where}: status must be one of {sorted(STATUSES)}")
    return errors


def gate(review_dir: str | Path) -> dict[str, Any]:
    root = Path(review_dir)
    probe_dir = root / "probes"
    issues: list[str] = []
    counts = {"high": 0, "medium": 0, "low": 0}
    open_high = 0

    for name in PROBES:
        path = probe_dir / f"{name}.json"
        if not path.exists():
            issues.append(f"missing required probe: {name}")
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            issues.append(f"{name}: invalid JSON ({exc})")
            continue
        if not isinstance(payload, dict):
            issues.append(f"{name}: payload must be an object")
            continue
        issues.extend(_validate_findings(name, payload))
        if payload.get("error"):
            issues.append(f"{name}: probe reported error: {payload['error']}")
        for f in payload.get("findings", []):
            if not isinstance(f, dict):
                continue
            sev = f.get("severity")
            if sev in counts:
                counts[sev] += 1
            if sev == "high" and f.get("status") == "open":
                open_high += 1

    for name in OPTIONAL:
        path = probe_dir / f"{name}.json"
        if path.exists():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                issues.extend(_validate_findings(name, payload))
            except json.JSONDecodeError as exc:
                issues.append(f"{name}: invalid JSON ({exc})")

    verdict = "pass" if not issues and open_high == 0 else "block"
    reasons = list(issues)
    if open_high:
        reasons.append(f"{open_high} open high-severity finding(s)")
    return {"verdict": verdict, "ok": verdict == "pass", "counts": counts,
            "open_high": open_high, "reasons": reasons}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("review_dir")
    args = ap.parse_args(argv)
    report = gate(args.review_dir)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
