"""Record the release-quality Ruff baseline without changing source files."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUFF = ROOT / ".venv/bin/ruff"


def main() -> int:
    fmt = subprocess.run(
        [str(RUFF), "format", "--check", "."], cwd=ROOT, text=True, capture_output=True
    )
    lint = subprocess.run(
        [str(RUFF), "check", ".", "--output-format", "json"],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    try:
        findings = json.loads(lint.stdout or "[]")
    except json.JSONDecodeError:
        findings = []
    categories = {
        "AUTO_FIX_SAFE": {"UP", "I", "F", "SIM", "RET", "RUF"},
        "IMPORT_ORDER": {"I"},
        "UNUSED_IMPORT": {"F401"},
        "UNUSED_VARIABLE": {"F841"},
        "STYLE": {"E", "UP", "SIM", "RET", "C4", "PERF", "PIE"},
        "TYPE_RELATED": set(),
        "REAL_CODE_SMELL": {"B"},
        "INTENTIONAL_EXCEPTION": set(),
    }
    counts = dict.fromkeys(categories, 0)
    for finding in findings:
        code = finding.get("code", "")
        if code == "I001":
            counts["IMPORT_ORDER"] += 1
        elif code == "F401":
            counts["UNUSED_IMPORT"] += 1
        elif code == "F841":
            counts["UNUSED_VARIABLE"] += 1
        elif code.startswith("B"):
            counts["REAL_CODE_SMELL"] += 1
        else:
            counts["STYLE"] += 1
    report = {
        "source": "direct ruff invocation",
        "format_returncode": fmt.returncode,
        "format_output": fmt.stdout + fmt.stderr,
        "lint_returncode": lint.returncode,
        "lint_count": len(findings),
        "lint_findings": findings,
        "classification_counts": counts,
    }
    out = ROOT / "artifacts/quality/ruff-baseline.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                k: report[k]
                for k in (
                    "format_returncode",
                    "lint_returncode",
                    "lint_count",
                    "classification_counts",
                )
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
