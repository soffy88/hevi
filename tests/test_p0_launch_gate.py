"""Tests for pipeline.launch_gate: ready only when every check passes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import hevi.capabilities as caps
from hevi.capabilities.launch_gate import (
    NEW_CAPABILITIES,
    REQUIRED_CAPABILITIES,
    check_launch,
    write_report,
)
from hevi.capabilities.project_handoff import create_project
from hevi.capabilities.project_snapshot import create_snapshot
from hevi.capabilities.registry import get
from hevi.capabilities.spend_ledger import freeze_batch


def _board() -> list[dict]:
    return [{"shot_id": "S01", "visual": "开场", "duration_sec": 5}]


def _ready_project(tmp_path: Path) -> Path:
    root = tmp_path / "film"
    create_project(root, title="demo")
    create_snapshot(root, label="first")
    create_snapshot(root, label="second")
    freeze_batch(root / "spend_ledger.json", batch_id="b1",
                 storyboard=_board(), confirmed=True, smoke_passed=True,
                 batch_size=1, unit_price=1.0)
    return root


def test_capability_registered_and_six_new_names() -> None:
    assert get("pipeline.launch_gate").name == "pipeline.launch_gate"
    assert len(NEW_CAPABILITIES) == 6
    assert "pipeline.project_handoff" in REQUIRED_CAPABILITIES
    assert "pipeline.spend_brake" in REQUIRED_CAPABILITIES


def test_gate_ready_when_all_checks_pass(tmp_path: Path, monkeypatch) -> None:
    import hevi.capabilities.launch_gate as gate_mod
    project = _ready_project(tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(gate_mod, "_read_commit", lambda r: {
        "ok": True, "commit": "abc123", "version": "test", "detail": ""})
    report = check_launch(repo_root=repo, project_root=project,
                          regression_tests=["tests/test_project_handoff.py"])
    assert report["ready"] is True
    assert report["failures"] == []
    assert report["commit"] == "abc123"
    by_name = {c["name"]: c for c in report["checks"]}
    assert by_name["rollback_point"]["snapshot_count"] == 2
    assert by_name["rollback_point"]["rollback_snapshot_id"]
    assert by_name["regression_tests"]["tests"]
    out = write_report(report, tmp_path / "launch_readiness.json")
    stored = json.loads(out.read_text(encoding="utf-8"))
    assert stored["ready"] is True


def test_gate_not_ready_without_rollback_snapshot(tmp_path: Path, monkeypatch) -> None:
    import hevi.capabilities.launch_gate as gate_mod
    root = tmp_path / "film"
    create_project(root)
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(gate_mod, "_read_commit", lambda r: {
        "ok": True, "commit": "abc123", "version": "test", "detail": ""})
    report = check_launch(repo_root=repo, project_root=root,
                          regression_tests=["tests/test_project_handoff.py"])
    assert report["ready"] is False
    assert any("rollback_point" in f for f in report["failures"])


def test_gate_not_ready_without_commit(tmp_path: Path, monkeypatch) -> None:
    import hevi.capabilities.launch_gate as gate_mod
    project = _ready_project(tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(gate_mod, "_read_commit", lambda r: {
        "ok": False, "commit": None, "version": None,
        "detail": "git failed"})
    report = check_launch(repo_root=repo, project_root=project,
                          regression_tests=["tests/test_project_handoff.py"])
    assert report["ready"] is False
    assert any("version_commit" in f for f in report["failures"])


def test_gate_lists_missing_capability(tmp_path: Path, monkeypatch) -> None:
    import hevi.capabilities.launch_gate as gate_mod
    project = _ready_project(tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(gate_mod, "_read_commit", lambda r: {
        "ok": True, "commit": "abc123", "version": "test", "detail": ""})
    report = check_launch(
        repo_root=repo, project_root=project,
        regression_tests=["tests/test_project_handoff.py"],
        required_capabilities=("pipeline.project_graph", "no.such.cap"))
    assert report["ready"] is False
    by_name = {c["name"]: c for c in report["checks"]}
    assert "no.such.cap" in by_name["capabilities"]["missing"]


def test_gate_empty_regression_list_fails(tmp_path: Path, monkeypatch) -> None:
    import hevi.capabilities.launch_gate as gate_mod
    project = _ready_project(tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(gate_mod, "_read_commit", lambda r: {
        "ok": True, "commit": "abc123", "version": "test", "detail": ""})
    report = check_launch(repo_root=repo, project_root=project,
                          regression_tests=[])
    assert report["ready"] is False
    assert any("regression_tests" in f for f in report["failures"])
