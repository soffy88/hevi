"""Line catalog qualification status comes from real qualification evidence.

Only the autonomous-production round whose ``git_sha`` matches the current
HEAD counts: completed lines render QUALIFIED with that round's short SHA,
blocked/failed lines render UNQUALIFIED with their blocker category, and
lines without a record (or without any HEAD-matching round) stay plain
UNQUALIFIED.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

HEAD = "a" * 40
STALE = "b" * 40


def _load_generator():
    path = Path(__file__).resolve().parents[1] / "scripts" / "generate_line_catalog.py"
    spec = importlib.util.spec_from_file_location("generate_line_catalog_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _write_line(lines_dir: Path, line_id: str) -> None:
    (lines_dir / f"{line_id}.yaml").write_text(
        f"id: {line_id}\n"
        "version: '1'\n"
        f"summary: {line_id} summary\n"
        "render_runtime: remotion\n"
        "tools: [tool.a]\n"
        "pipeline:\n"
        "  stages:\n"
        "    - name: intake\n",
        encoding="utf-8",
    )


def _write_summary(evidence_dir: Path, sha: str, summary: dict) -> None:
    round_dir = evidence_dir / sha
    round_dir.mkdir(parents=True)
    summary.setdefault("git_sha", sha)
    (round_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False), encoding="utf-8"
    )


@pytest.fixture()
def catalog_env(tmp_path: Path) -> tuple[Path, Path]:
    lines_dir = tmp_path / "lines"
    lines_dir.mkdir()
    for line_id in ("line_done", "line_blocked", "line_failed", "line_missing"):
        _write_line(lines_dir, line_id)
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    # A stale round for another SHA claims everything completed; the
    # HEAD-matching lookup must ignore it (it also sorts after HEAD here).
    _write_summary(
        evidence_dir,
        STALE,
        {"lines": [{"line": "line_missing", "status": "completed", "blocker": None}]},
    )
    _write_summary(
        evidence_dir,
        HEAD,
        {
            "lines": [
                {"line": "line_done", "status": "completed", "blocker": None},
                {"line": "line_blocked", "status": "blocked", "blocker": "provider down"},
                {"line": "line_failed", "status": "failed", "blocker": "boom"},
            ],
            "blocker_matrix": [
                {"line": "line_blocked", "status": "blocked",
                 "root_cause": "PROVIDER_NETWORK", "failed_gate": "PROVIDER_NETWORK"},
            ],
        },
    )
    return lines_dir, evidence_dir


def _row(catalog: str, line_id: str) -> str:
    rows = [line for line in catalog.splitlines() if line.startswith(f"| {line_id} |")]
    assert len(rows) == 1
    return rows[0]


def test_status_mapping_from_head_matching_round(catalog_env: tuple[Path, Path]) -> None:
    mod = _load_generator()
    lines_dir, evidence_dir = catalog_env
    catalog = mod.build_catalog(lines_dir, evidence_dir, HEAD)
    assert _row(catalog, "line_done").endswith("| QUALIFIED | aaaaaaa |")
    assert _row(catalog, "line_blocked").endswith("| UNQUALIFIED（PROVIDER_NETWORK） | — |")
    # No blocker_matrix entry -> the qualification script's own fallback class.
    assert _row(catalog, "line_failed").endswith("| UNQUALIFIED（UNCLASSIFIED_FAILURE） | — |")
    assert _row(catalog, "line_missing").endswith("| UNQUALIFIED | — |")


def test_no_head_matching_round_means_all_unqualified(
    catalog_env: tuple[Path, Path],
) -> None:
    mod = _load_generator()
    lines_dir, evidence_dir = catalog_env
    catalog = mod.build_catalog(lines_dir, evidence_dir, "c" * 40)
    for line_id in ("line_done", "line_blocked", "line_failed", "line_missing"):
        assert _row(catalog, line_id).endswith("| UNQUALIFIED | — |")


def test_generation_is_deterministic(catalog_env: tuple[Path, Path]) -> None:
    mod = _load_generator()
    lines_dir, evidence_dir = catalog_env
    assert mod.build_catalog(lines_dir, evidence_dir, HEAD) == mod.build_catalog(
        lines_dir, evidence_dir, HEAD
    )


def test_main_writes_catalog(
    catalog_env: tuple[Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mod = _load_generator()
    lines_dir, evidence_dir = catalog_env
    output = tmp_path / "out" / "line_catalog.md"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "generate_line_catalog.py",
            "--lines-dir", str(lines_dir),
            "--evidence-dir", str(evidence_dir),
            "--head-sha", HEAD,
            "--output", str(output),
        ],
    )
    assert mod.main() == 0
    catalog = output.read_text(encoding="utf-8")
    assert _row(catalog, "line_done").endswith("| QUALIFIED | aaaaaaa |")
