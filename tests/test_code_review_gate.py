"""S17: optional code-review gate (MIT method re-expressed)."""

from __future__ import annotations

import json
from pathlib import Path

from hevi.qa.code_review_gate import gate


def _write(root: Path, name: str, findings, error=None):
    directory = root / "probes"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{name}.json").write_text(
        json.dumps({"findings": findings, "error": error}), encoding="utf-8"
    )


def _clean(root: Path):
    for probe in ("behavior-review", "test-coverage", "repo-guard"):
        _write(root, probe, [
            {"location": "hevi/x.py:1", "summary": "ok", "evidence": "checked",
             "severity": "low", "status": "reconciled"},
        ])


def test_clean_gate_passes(tmp_path: Path):
    _clean(tmp_path)
    assert gate(tmp_path)["verdict"] == "pass"


def test_missing_probe_blocks(tmp_path: Path):
    _write(tmp_path, "behavior-review", [])
    report = gate(tmp_path)
    assert report["verdict"] == "block"
    assert any("missing required probe" in reason for reason in report["reasons"])


def test_open_high_blocks(tmp_path: Path):
    _clean(tmp_path)
    _write(tmp_path, "repo-guard", [
        {"location": "hevi/x.py:9", "summary": "leak", "evidence": "diff",
         "severity": "high", "status": "open"},
    ])
    report = gate(tmp_path)
    assert report["verdict"] == "block" and report["open_high"] == 1


def test_critical_severity_is_rejected(tmp_path: Path):
    _clean(tmp_path)
    _write(tmp_path, "behavior-review", [
        {"location": "x", "summary": "s", "evidence": "e",
         "severity": "critical", "status": "open"},
    ])
    assert gate(tmp_path)["verdict"] == "block"
