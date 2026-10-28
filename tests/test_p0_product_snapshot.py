"""Tests for pipeline.project_snapshot: snapshots, restore, stale, conflict."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import hevi.capabilities as caps
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.project_handoff import create_project
from hevi.capabilities.project_snapshot import (
    DEFAULT_KEEP,
    check_stale,
    create_snapshot,
    guarded_write,
    list_snapshots,
    restore_snapshot,
    save_with_conflict,
    schedule_periodic_snapshot,
)
from hevi.capabilities.registry import get


def test_capability_registered_and_default_keep_is_20() -> None:
    assert get("pipeline.project_snapshot").name == "pipeline.project_snapshot"
    assert DEFAULT_KEEP == 20


def test_snapshot_and_restore_backs_up_first(tmp_path: Path) -> None:
    root = tmp_path / "film"
    create_project(root, title="v1")
    snap1 = create_snapshot(root, label="first")
    create_project(root, title="v2")
    snap2 = create_snapshot(root, label="second")
    assert snap1["version"] == 1 and snap2["version"] == 2
    restored = restore_snapshot(root, snap1["snapshot_id"])
    assert restored["backup_snapshot_id"] != snap1["snapshot_id"]
    assert restored["backup_label"] == "pre-restore-backup"
    assert restored["restored_manifest"] is True
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["title"] == "v1"
    # The pre-restore backup is itself a snapshot on disk.
    assert any(s["snapshot_id"] == restored["backup_snapshot_id"]
               for s in list_snapshots(root))


def test_retention_default_keeps_20_and_custom_keep(tmp_path: Path) -> None:
    root = tmp_path / "film"
    create_project(root)
    for _ in range(22):
        create_snapshot(root)
    assert len(list_snapshots(root)) == 20
    root2 = tmp_path / "film2"
    create_project(root2)
    for _ in range(5):
        create_snapshot(root2, keep=3)
    assert len(list_snapshots(root2)) == 3


def test_stale_write_refused_and_newer_write_allowed(tmp_path: Path) -> None:
    state = tmp_path / "state.json"
    guarded_write(state, {"version": 5, "updated_at": "2026-10-28T10:00:00Z",
                          "title": "new"})
    with pytest.raises(CapabilityError, match="old content"):
        guarded_write(state, {"version": 4,
                              "updated_at": "2026-10-28T09:00:00Z",
                              "title": "old"})
    with pytest.raises(CapabilityError, match="old content"):
        guarded_write(state, {"version": 5,
                              "updated_at": "2026-10-28T09:00:00Z",
                              "title": "older-same-version"})
    stored = json.loads(state.read_text(encoding="utf-8"))
    assert stored["title"] == "new"
    guarded_write(state, {"version": 6,
                          "updated_at": "2026-10-28T11:00:00Z",
                          "title": "newer"})
    assert json.loads(state.read_text(encoding="utf-8"))["title"] == "newer"
    assert check_stale(5, "2026-10-28T10:00:00Z",
                       4, "2026-10-28T09:00:00Z")["stale"] is True
    assert check_stale(5, "2026-10-28T10:00:00Z",
                       6, "2026-10-28T11:00:00Z")["stale"] is False


def test_conflict_stops_auto_commit_and_keeps_draft(tmp_path: Path) -> None:
    root = tmp_path / "film"
    create_project(root)
    result = save_with_conflict(
        root, {"title": "local-edit"},
        base_version=1, live_version=3, draft_version=2)
    assert result["status"] == "conflicted"
    assert result["auto_commit"] is False
    draft_path = Path(result["draft_path"])
    assert draft_path.is_file()
    assert json.loads(draft_path.read_text(encoding="utf-8"))["draft"] == {
        "title": "local-edit"}
    # Live manifest untouched by the conflict path.
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest.get("title") != "local-edit"


def test_no_conflict_when_only_one_side_moved(tmp_path: Path) -> None:
    root = tmp_path / "film"
    create_project(root)
    result = save_with_conflict(
        root, {"title": "local-edit"},
        base_version=1, live_version=1, draft_version=2)
    assert result["status"] == "clean"
    assert result["draft_path"] is None


def test_restore_unknown_snapshot_refused(tmp_path: Path) -> None:
    root = tmp_path / "film"
    create_project(root)
    with pytest.raises(CapabilityError, match="snapshot not found"):
        restore_snapshot(root, "snap-9999-nope")


def test_periodic_schedule_is_unconnected_stub(tmp_path: Path) -> None:
    root = tmp_path / "film"
    create_project(root)
    result = schedule_periodic_snapshot(root, interval_minutes=5)
    assert result["scheduled"] is False
    assert "未接" in result["reason"] or "未接入" in result["reason"]
