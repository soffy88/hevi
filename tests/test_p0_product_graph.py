"""Tests for pipeline.project_graph: nodes, edges, templates, replay."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import hevi.capabilities as caps
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.project_graph import (
    NODE_TYPES,
    attach_graph_to_manifest,
    create_graph,
    edges_of,
    from_json,
    rebind_template,
    replay_order,
    save_template,
    to_json,
    topological_order,
    validate_graph,
)
from hevi.capabilities.project_handoff import create_project
from hevi.capabilities.registry import get


def _chain() -> list[dict]:
    return [
        {"node_id": "board", "type": "storyboard", "inputs": [],
         "artifact": "board.json"},
        {"node_id": "frame", "type": "first_frame", "inputs": ["board"],
         "artifact": "frame.png"},
        {"node_id": "clip", "type": "motion", "inputs": ["frame"],
         "artifact": "clip.mp4"},
        {"node_id": "voice", "type": "narration", "inputs": ["board"],
         "artifact": "voice.wav"},
        {"node_id": "subs", "type": "subtitle", "inputs": ["voice", "clip"],
         "artifact": "subs.srt"},
        {"node_id": "cover", "type": "cover", "inputs": ["frame"],
         "artifact": "cover.png"},
    ]


def test_capability_registered() -> None:
    assert get("pipeline.project_graph").name == "pipeline.project_graph"


def test_all_six_node_types_present() -> None:
    assert set(NODE_TYPES) >= {
        "storyboard", "first_frame", "motion", "narration",
        "subtitle", "cover",
    }


def test_create_edges_and_replay_order_positive() -> None:
    graph = create_graph(_chain())
    edges = edges_of(graph)
    assert {"from": "board", "to": "frame"} in edges
    assert {"from": "frame", "to": "clip"} in edges
    order = replay_order(graph)
    assert order.index("board") < order.index("frame") < order.index("clip")
    assert order.index("voice") < order.index("subs")
    assert order.index("clip") < order.index("subs")


def test_json_round_trip() -> None:
    graph = create_graph(_chain())
    restored = from_json(to_json(graph))
    assert [n["node_id"] for n in restored["nodes"]] == [
        n["node_id"] for n in graph["nodes"]
    ]
    assert topological_order(restored) == topological_order(graph)


def test_template_requires_success_and_rebind_only_rebinds() -> None:
    graph = create_graph(_chain())
    with pytest.raises(CapabilityError, match="success"):
        save_template(graph, "tpl-1", {"run_id": "r1", "status": "failed"})
    template = save_template(
        graph, "tpl-1", {"run_id": "r1", "status": "success"})
    rebound = rebind_template(
        template, {"frame": "frame-v2.png", "board": {"params": {"shots": 3}}})
    assert rebound["template_id"] == "tpl-1"
    by_id = {n["node_id"]: n for n in rebound["nodes"]}
    assert by_id["frame"]["artifact"] == "frame-v2.png"
    assert by_id["frame"]["type"] == "first_frame"
    assert by_id["frame"]["inputs"] == ["board"]
    assert by_id["board"]["params"]["shots"] == 3
    # Wiring unchanged: same edges as the original graph.
    assert rebound["edges"] == edges_of(graph)


def test_rebind_unknown_node_refused() -> None:
    template = save_template(
        create_graph(_chain()), "tpl-1",
        {"run_id": "r1", "status": "success"})
    with pytest.raises(CapabilityError, match="unknown node"):
        rebind_template(template, {"nope": "x.png"})


def test_missing_input_named_and_refused() -> None:
    bad = [{"node_id": "clip", "type": "motion", "inputs": ["ghost"]}]
    report = validate_graph({"nodes": bad})
    assert report["ok"] is False
    assert any(p["kind"] == "missing_input" and p["missing_input"] == "ghost"
               for p in report["problems"])
    with pytest.raises(CapabilityError, match="ghost"):
        create_graph(bad)


def test_cycle_named_and_refused() -> None:
    cyclic = [
        {"node_id": "a", "type": "storyboard", "inputs": ["b"]},
        {"node_id": "b", "type": "first_frame", "inputs": ["a"]},
    ]
    report = validate_graph({"nodes": cyclic})
    assert report["ok"] is False
    assert any(p["kind"] == "cycle" for p in report["problems"])
    with pytest.raises(CapabilityError, match="cycle"):
        create_graph(cyclic)


def test_unknown_type_and_duplicate_refused() -> None:
    with pytest.raises(CapabilityError, match="unknown type"):
        create_graph([{"node_id": "x", "type": "video3d", "inputs": []}])
    with pytest.raises(CapabilityError, match="duplicate"):
        create_graph([
            {"node_id": "x", "type": "storyboard", "inputs": []},
            {"node_id": "x", "type": "cover", "inputs": []},
        ])


def test_attach_graph_to_manifest(tmp_path: Path) -> None:
    root = tmp_path / "film"
    create_project(root, title="demo")
    data = attach_graph_to_manifest(root, create_graph(_chain()))
    assert data["graph_replay_order"][0] == "board"
    stored = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    assert stored["graph"]["nodes"][0]["node_id"] == "board"
    assert stored["stages"]["reference"]["status"] == "pending"
