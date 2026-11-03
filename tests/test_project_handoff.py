"""Tests for pipeline.project_handoff: fixed directories, manifest, gate."""

from __future__ import annotations

from pathlib import Path

import pytest

import hevi.capabilities as caps
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.project_handoff import (
    STAGE_DIRS,
    STAGES,
    create_project,
    gate_for_stage,
    record_step,
    validate_manifest,
)


def _write(root: Path, rel: str) -> str:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("x", encoding="utf-8")
    return rel


def test_create_makes_all_stage_dirs_and_manifest(tmp_path: Path) -> None:
    root = tmp_path / "film"
    data = create_project(root, title="demo")
    assert data["title"] == "demo"
    for stage in STAGES:
        assert (root / STAGE_DIRS[stage]).is_dir()
    assert (root / "manifest.json").is_file()
    assert all(v["status"] == "pending" for v in data["stages"].values())


def test_gate_blocks_and_names_missing_stages(tmp_path: Path) -> None:
    root = tmp_path / "film"
    create_project(root)
    ref = _write(root, "00_reference/notes.md")
    record_step(root, "reference", [], [ref])
    gate = gate_for_stage(root, "subtitle")
    assert gate["ready"] is False
    blocked = [b["stage"] for b in gate["blockers"]]
    # topic and script are unrecorded; edit and broll are too.
    assert "topic" in blocked and "script" in blocked
    assert "edit" in blocked and "broll" in blocked
    assert "reference" not in blocked


def test_gate_passes_once_prior_stages_recorded(tmp_path: Path) -> None:
    root = tmp_path / "film"
    create_project(root)
    for stage, rel in (
        ("reference", "00_reference/notes.md"),
        ("topic", "01_topic/topic.md"),
        ("script", "02_script/script.md"),
    ):
        record_step(root, stage, [], [_write(root, rel)])
    gate = gate_for_stage(root, "edit")
    assert gate["ready"] is True
    assert gate["blockers"] == []


def test_record_refuses_missing_output_and_gate_spots_deleted_file(tmp_path: Path) -> None:
    root = tmp_path / "film"
    create_project(root)
    with pytest.raises(CapabilityError):
        record_step(root, "reference", [], ["00_reference/gone.md"])
    ref = _write(root, "00_reference/notes.md")
    record_step(root, "reference", [], [ref])
    (root / ref).unlink()
    gate = gate_for_stage(root, "topic")
    assert gate["ready"] is False
    assert gate["blockers"][0]["missing_files"] == [ref]
    problems = validate_manifest(root)
    assert problems["valid"] is False
    assert problems["problems"][0]["missing_files"] == [ref]


def test_unknown_stage_raises(tmp_path: Path) -> None:
    root = tmp_path / "film"
    create_project(root)
    with pytest.raises(CapabilityError):
        gate_for_stage(root, "nope")


def test_registry_create_and_gate(tmp_path: Path) -> None:
    cap = caps.get("pipeline.project_handoff")
    root = tmp_path / "film"
    cap.render_safe(
        {"project_root": str(root), "action": "create", "title": "demo"},
        tmp_path / "out", duration=0.0, aspect="16:9", seed=1,
    )
    assert (root / "manifest.json").is_file()
    result = cap.render_safe(
        {"project_root": str(root), "action": "gate", "stage": "topic"},
        tmp_path / "out2", duration=0.0, aspect="16:9", seed=1,
    )
    assert result.qa["result"]["ready"] is False
