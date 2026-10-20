#!/usr/bin/env python3
"""Generate the line catalog from the YAML authority, never a hard-coded count.

Qualification status is read from real qualification evidence: the
``summary.json`` of the autonomous-production qualification round whose
``git_sha`` matches the current repository HEAD. Rounds for any other SHA
are ignored — without a HEAD-matching round every line is UNQUALIFIED.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import yaml

DEFAULT_EVIDENCE_DIR = Path("artifacts/qualification/autonomous-production")
NO_SHA = "—"


def current_head_sha() -> str | None:
    """Current repository HEAD, or None when it cannot be resolved."""
    try:
        sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None
    return sha or None


def _blocker_category(summary: dict, line_id: str) -> str:
    """Blocker classification for one line from the summary's blocker matrix.

    Mirrors ``_blocker_matrix_row`` in qualify_autonomous_production.py: the
    matrix ``root_cause`` (fallback ``failed_gate``) is the classification.
    Summaries without a matrix entry fall back to UNCLASSIFIED_FAILURE, the
    same fallback classification the qualification script itself uses.
    """
    for row in summary.get("blocker_matrix") or []:
        if not isinstance(row, dict) or row.get("line") != line_id:
            continue
        category = str(row.get("root_cause") or row.get("failed_gate") or "").strip()
        if category:
            return category.replace("|", "/")
    return "UNCLASSIFIED_FAILURE"


def load_qualification_statuses(
    evidence_dir: Path, head_sha: str | None
) -> dict[str, tuple[str, str]]:
    """Map line id -> (qualification status, last qualified SHA) for one round.

    Only the round whose ``git_sha`` equals ``head_sha`` counts. Within it,
    ``completed`` lines are QUALIFIED with the round's short SHA; lines with
    any other recorded status are UNQUALIFIED with their blocker category;
    lines without a record are absent here (rendered plain UNQUALIFIED).
    """
    if not head_sha or not evidence_dir.is_dir():
        return {}
    for summary_path in sorted(evidence_dir.glob("*/summary.json")):
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(summary, dict) or str(summary.get("git_sha") or "") != head_sha:
            continue
        statuses: dict[str, tuple[str, str]] = {}
        for row in summary.get("lines") or []:
            if not isinstance(row, dict) or not row.get("line"):
                continue
            line_id = str(row["line"])
            if row.get("status") == "completed":
                statuses[line_id] = ("QUALIFIED", head_sha[:7])
            else:
                category = _blocker_category(summary, line_id)
                statuses[line_id] = (f"UNQUALIFIED（{category}）", NO_SHA)
        return statuses
    return {}


def build_catalog(lines_dir: Path, evidence_dir: Path, head_sha: str | None) -> str:
    statuses = load_qualification_statuses(evidence_dir, head_sha)
    rows: list[str] = [
        "# HEVI Studio line catalog",
        "",
        "Generated from `hevi/studio/lines/*.yaml`; do not edit manually.",
        "",
        "| Name | Version | Description | Stages | Provider dependencies | Renderer/backend | Qualification status | Last qualified SHA |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for path in sorted(lines_dir.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        stages = ", ".join(stage["name"] for stage in data.get("pipeline", {}).get("stages", []))
        tools = ", ".join(data.get("tools", []))
        status, last_sha = statuses.get(str(data["id"]), ("UNQUALIFIED", NO_SHA))
        rows.append(
            f"| {data['id']} | {data.get('version', '1')} | {data.get('summary', '')} | {stages} | {tools} | {data.get('render_runtime', '')} | {status} | {last_sha} |"
        )
    return "\n".join(rows) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lines-dir", type=Path, default=Path("hevi/studio/lines"))
    parser.add_argument("--output", type=Path, default=Path("docs/generated/line_catalog.md"))
    parser.add_argument("--evidence-dir", type=Path, default=DEFAULT_EVIDENCE_DIR)
    parser.add_argument(
        "--head-sha",
        default=None,
        help="repository HEAD to match qualification evidence against "
        "(default: resolved with git rev-parse HEAD)",
    )
    args = parser.parse_args()
    head_sha = args.head_sha or current_head_sha()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        build_catalog(args.lines_dir, args.evidence_dir, head_sha), encoding="utf-8"
    )
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
