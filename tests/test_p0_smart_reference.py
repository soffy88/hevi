"""Tests for pipeline.smart_reference: parse, skip, graph/manifest write."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import hevi.capabilities as caps
from hevi.capabilities.project_graph import create_graph
from hevi.capabilities.project_handoff import create_project
from hevi.capabilities.registry import get
from hevi.capabilities.smart_reference import (
    apply_references_to_graph,
    attach_references_to_manifest,
    parse_references,
)


def _materials() -> list[dict]:
    return [
        {"picture_number": 1, "asset_id": "asset-1", "path": "img1.png"},
        {"picture_number": 2, "asset_id": "asset-2", "path": "img2.png"},
    ]


def test_capability_registered() -> None:
    assert get("pipeline.smart_reference").name == "pipeline.smart_reference"


def test_parse_three_spellings_resolve(tmp_path: Path) -> None:
    parsed = parse_references(
        "用图1开场，接图片2特写，再看图 1一眼", _materials())
    assert parsed["resolved_count"] == 3
    assert parsed["skipped_count"] == 0
    assert parsed["references"][0]["asset_id"] == "asset-1"
    assert parsed["references"][1]["asset_id"] == "asset-2"
    assert parsed["references"][2]["raw"] == "图 1"


def test_unconnected_reference_skipped_not_guessed() -> None:
    parsed = parse_references("用图9收尾", _materials())
    assert len(parsed["references"]) == 1
    entry = parsed["references"][0]
    assert entry["status"] == "skipped"
    assert entry["asset_id"] is None
    assert "unconnected" in entry["reason"]


def test_ambiguous_reference_skipped_not_guessed() -> None:
    materials = _materials() + [
        {"picture_number": 1, "asset_id": "asset-1-dup", "path": "img1b.png"},
    ]
    parsed = parse_references("用图1开场", materials)
    entry = parsed["references"][0]
    assert entry["status"] == "skipped"
    assert entry["asset_id"] is None
    assert "ambiguous" in entry["reason"]


def test_mixed_prompt_keeps_resolved_and_skipped_separate() -> None:
    parsed = parse_references("图1可用，图3未接", _materials())
    assert parsed["references"][0]["status"] == "resolved"
    assert parsed["references"][1]["status"] == "skipped"
    assert parsed["resolved_count"] == 1
    assert parsed["skipped_count"] == 1


def test_mapping_written_to_graph_and_manifest(tmp_path: Path) -> None:
    graph = create_graph([
        {"node_id": "frame", "type": "first_frame", "inputs": []},
    ])
    with_refs = apply_references_to_graph(
        graph, "参考图1", _materials())
    assert with_refs["references"][0]["asset_id"] == "asset-1"
    root = tmp_path / "film"
    create_project(root)
    data = attach_references_to_manifest(
        root, with_refs["references"])
    assert data["references"][0]["asset_id"] == "asset-1"
    stored = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    assert stored["references"][0]["status"] == "resolved"


def test_no_reference_prompt_yields_empty_mapping() -> None:
    parsed = parse_references("一段没有图片引用的旁白", _materials())
    assert parsed["references"] == []
