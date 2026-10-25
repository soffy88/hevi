"""Tests for hevi.canvas.workflow_adapter.

All fixtures are invented for this test file only: generic node ids,
placeholder params and placeholder artifact paths. No real plot,
character, or production material is reused here, and no generation
or network call is made (preflight only reads node configs).
"""

from __future__ import annotations

import copy

import pytest

from hevi.canvas.workflow_adapter import (
    WORKFLOW_TO_CANVAS,
    WorkflowAdapterError,
    apply_run_result_to_graph,
    as_graph_service_payload,
    canvas_edge_warnings,
    graph_to_workflow,
    planned_graph,
    plan_rerun,
    rerun_order,
    run_preflight_for_workflow,
    workflow_to_graph,
)
from hevi.capabilities.canvas_workflow import create_workflow


def _dag():
    # All seven workflow types in one invented chain:
    # script -> first_frame -> video -> subtitle -> assemble,
    # script -> audio -> assemble, script -> tail_frame -> video.
    return create_workflow(
        [
            {"node_id": "w_script", "type": "script",
             "params": {"title": "invented title"}},
            {"node_id": "w_frame", "type": "first_frame",
             "inputs": ["w_script"], "params": {"prompt": "invented frame"}},
            {"node_id": "w_tail", "type": "tail_frame",
             "inputs": ["w_script"], "params": {"prompt": "invented tail"}},
            {"node_id": "w_video", "type": "video",
             "inputs": ["w_frame", "w_tail"],
             "params": {"duration_s": 5}},
            {"node_id": "w_audio", "type": "audio",
             "inputs": ["w_script"], "params": {"voice": "invented"},
             "status": "done", "artifact": "fake/audio.wav"},
            {"node_id": "w_sub", "type": "subtitle",
             "inputs": ["w_video"], "params": {"language": "en"}},
            {"node_id": "w_asm", "type": "assemble",
             "inputs": ["w_video", "w_audio", "w_sub"]},
        ]
    )


def _by_id(graph):
    return {n["node_id"]: n for n in graph["nodes"]}


# ── mapping table ──────────────────────────────────────────────────────────

def test_mapping_table_covers_all_workflow_types():
    assert set(WORKFLOW_TO_CANVAS) == {
        "script", "first_frame", "tail_frame", "video",
        "audio", "subtitle", "assemble",
    }
    assert WORKFLOW_TO_CANVAS["script"] == "script"
    assert WORKFLOW_TO_CANVAS["first_frame"] == "image"
    assert WORKFLOW_TO_CANVAS["tail_frame"] == "image"
    assert WORKFLOW_TO_CANVAS["video"] == "video"
    assert WORKFLOW_TO_CANVAS["audio"] == "audio"
    assert WORKFLOW_TO_CANVAS["subtitle"] == "text"
    assert WORKFLOW_TO_CANVAS["assemble"] == "video"


def test_workflow_to_graph_uses_native_canvas_types():
    nodes = _by_id(workflow_to_graph(_dag()))
    assert nodes["w_script"]["node_type"] == "script"
    assert nodes["w_frame"]["node_type"] == "image"
    assert nodes["w_tail"]["node_type"] == "image"
    assert nodes["w_video"]["node_type"] == "video"
    assert nodes["w_audio"]["node_type"] == "audio"
    assert nodes["w_sub"]["node_type"] == "text"
    assert nodes["w_asm"]["node_type"] == "video"
    # Workflow identity rides in config, params stay flattened for executors.
    assert nodes["w_frame"]["config"]["workflow_type"] == "first_frame"
    assert nodes["w_frame"]["config"]["prompt"] == "invented frame"
    assert nodes["w_asm"]["config"]["workflow_type"] == "assemble"
    # Status: workflow done -> frontend completed, kept exactly in config.
    assert nodes["w_audio"]["status"] == "completed"
    assert nodes["w_audio"]["config"]["workflow_status"] == "done"
    assert nodes["w_audio"]["config"]["workflow_artifact"] == "fake/audio.wav"


def test_workflow_to_graph_edges_follow_inputs_in_order():
    graph = workflow_to_graph(_dag())
    pairs = [(e["from_node_id"], e["to_node_id"]) for e in graph["edges"]]
    assert pairs == [
        ("w_script", "w_frame"),
        ("w_script", "w_tail"),
        ("w_frame", "w_video"),
        ("w_tail", "w_video"),
        ("w_script", "w_audio"),
        ("w_video", "w_sub"),
        ("w_video", "w_asm"),
        ("w_audio", "w_asm"),
        ("w_sub", "w_asm"),
    ]
    assert all(e["edge_id"] == f"{a}__{b}" for e, (a, b) in zip(graph["edges"], pairs))


def test_auto_layout_puts_dependencies_in_earlier_columns():
    graph = workflow_to_graph(_dag())
    nodes = _by_id(graph)
    assert nodes["w_script"]["position"]["x"] < nodes["w_frame"]["position"]["x"]
    assert nodes["w_frame"]["position"]["x"] < nodes["w_video"]["position"]["x"]
    assert nodes["w_video"]["position"]["x"] < nodes["w_asm"]["position"]["x"]


def test_explicit_positions_win_and_unknown_position_errors():
    graph = workflow_to_graph(
        _dag(), positions={"w_script": {"x": 10, "y": 20}}
    )
    assert _by_id(graph)["w_script"]["position"] == {"x": 10, "y": 20}
    with pytest.raises(WorkflowAdapterError):
        workflow_to_graph(_dag(), positions={"nope": {"x": 0, "y": 0}})


# ── round-trips ────────────────────────────────────────────────────────────

def test_round_trip_workflow_graph_workflow_deep_equal():
    workflow = _dag()
    assert graph_to_workflow(workflow_to_graph(workflow)) == workflow


def test_round_trip_preserves_colliding_param_names():
    # A param literally named "workflow_type" must survive: the
    # adapter stashes it and restores it instead of overwriting it.
    workflow = create_workflow(
        [
            {"node_id": "s", "type": "script",
             "params": {"workflow_type": "param value", "nested": {"a": [1, 2]}}},
            {"node_id": "v", "type": "video", "inputs": ["s"],
             "params": {"workflow_status": "param status"}},
        ]
    )
    assert graph_to_workflow(workflow_to_graph(workflow)) == workflow


def test_round_trip_preserves_status_artifact_attempts_reason():
    workflow = create_workflow(
        [
            {"node_id": "s", "type": "script", "status": "failed",
             "attempts": 2, "artifact": None},
            {"node_id": "v", "type": "video", "inputs": ["s"],
             "status": "blocked", "attempts": 3, "reason": "max_retries_exceeded"},
        ]
    )
    assert graph_to_workflow(workflow_to_graph(workflow)) == workflow


def test_position_round_trip_via_include_position():
    graph = workflow_to_graph(
        _dag(), positions={"w_script": {"x": 7, "y": 9}}
    )
    workflow = graph_to_workflow(graph, include_position=True)
    assert workflow_to_graph(workflow) == graph


def test_graph_storage_shape_nodes_json_accepted():
    graph = workflow_to_graph(_dag())
    stored = {"nodes_json": graph["nodes"], "edges_json": graph["edges"]}
    assert graph_to_workflow(stored) == _dag()


def test_graph_without_workflow_meta_maps_native_types_only():
    graph = {
        "nodes": [
            {"node_id": "s", "node_type": "script", "config": {}},
            {"node_id": "v", "node_type": "video", "config": {}},
        ],
        "edges": [{"edge_id": "s__v", "from_node_id": "s", "to_node_id": "v"}],
    }
    workflow = graph_to_workflow(graph)
    assert [(n["node_id"], n["type"]) for n in workflow["nodes"]] == [
        ("s", "script"), ("v", "video"),
    ]
    assert workflow["nodes"][1]["inputs"] == ["s"]


# ── missing mapping / illegal edges: errors, never silent drops ───────────

def test_unmapped_canvas_types_error():
    for node_type in ("image", "text", "render"):
        graph = {
            "nodes": [{"node_id": "n", "node_type": node_type, "config": {}}],
            "edges": [],
        }
        with pytest.raises(WorkflowAdapterError):
            graph_to_workflow(graph)


def test_inconsistent_workflow_meta_errors():
    graph = {
        "nodes": [{"node_id": "n", "node_type": "image", "config": {
            "workflow_type": "video"}}],
        "edges": [],
    }
    with pytest.raises(WorkflowAdapterError):
        graph_to_workflow(graph)


def test_unknown_workflow_type_errors():
    with pytest.raises(WorkflowAdapterError):
        workflow_to_graph({"nodes": [{"node_id": "n", "type": "render"}]})


def test_edge_to_unknown_node_errors():
    graph = workflow_to_graph(_dag())
    graph["edges"].append(
        {"edge_id": "w_script__ghost", "from_node_id": "w_script",
         "to_node_id": "ghost"}
    )
    with pytest.raises(WorkflowAdapterError):
        graph_to_workflow(graph)


def test_duplicate_edge_errors():
    graph = workflow_to_graph(_dag())
    graph["edges"].append(dict(graph["edges"][0]))
    with pytest.raises(WorkflowAdapterError):
        graph_to_workflow(graph)


def test_cycle_graph_errors():
    graph = workflow_to_graph(_dag())
    graph["edges"].append(
        {"edge_id": "w_asm__w_script", "from_node_id": "w_asm",
         "to_node_id": "w_script"}
    )
    with pytest.raises(WorkflowAdapterError):
        graph_to_workflow(graph)


def test_canvas_edge_warnings_cured_matrix_no_false_positives():
    # 2026-10-25 cure: the canonical 7-type graph (including
    # script -> audio and video -> subtitle) is legal in the hevi
    # matrix, so it produces NO warnings -- and it now also passes
    # validate_graph on the ExecutorService path (see
    # tests/test_canvas_edge_matrix.py). The adapter still never
    # drops an edge: a genuinely illegal edge (audio -> text,
    # appended here only to probe the reporter) is warned, not dropped.
    graph = workflow_to_graph(_dag())
    assert canvas_edge_warnings(graph) == []
    assert graph_to_workflow(graph) == _dag()
    graph["edges"].append(
        {"edge_id": "probe__audio_text", "from_node_id": "w_audio",
         "to_node_id": "w_sub", "from_type": "audio", "to_type": "text"}
    )
    warnings = canvas_edge_warnings(graph)
    flagged = {(w["from_node_id"], w["to_node_id"]) for w in warnings}
    assert ("w_audio", "w_sub") in flagged
    assert ("w_video", "w_sub") not in flagged
    assert len(graph["edges"]) == 10  # probe edge kept, not dropped


# ── rerun semantics ────────────────────────────────────────────────────────

def test_rerun_order_includes_all_upstream_in_topo_order():
    order = rerun_order(_dag(), ["w_asm"])
    assert order.index("w_script") < order.index("w_frame")
    assert order.index("w_frame") < order.index("w_video")
    assert order.index("w_video") < order.index("w_asm")
    assert order.index("w_audio") < order.index("w_asm")
    assert len(order) == len(set(order)) == 7
    # Same result when the source is a graph instead of a workflow.
    assert rerun_order(workflow_to_graph(_dag()), ["w_asm"]) == order


def test_plan_skips_done_upstream_unless_selected():
    plan = {p["node_id"]: p for p in plan_rerun(_dag(), ["w_asm"])}
    assert plan["w_audio"]["action"] == "skip"
    assert plan["w_audio"]["reason"] == "already_done"
    assert plan["w_asm"]["action"] == "run"
    selected = {p["node_id"]: p for p in plan_rerun(_dag(), ["w_audio"])}
    assert selected["w_audio"]["action"] == "run"
    assert selected["w_audio"]["reason"] == "selected"
    assert selected["w_script"]["reason"] == "dependency"


def test_apply_result_caps_third_failure_at_blocked():
    graph = workflow_to_graph(_dag())
    for _ in range(2):
        graph = apply_run_result_to_graph(graph, "w_video", "failed")
        node = _by_id(graph)["w_video"]
        assert node["status"] == "failed"
        assert node["config"]["workflow_status"] == "failed"
    graph = apply_run_result_to_graph(graph, "w_video", "failed")
    node = _by_id(graph)["w_video"]
    assert node["status"] == "blocked"
    assert node["config"]["workflow_status"] == "blocked"
    assert node["config"]["workflow_attempts"] == 3
    assert node["config"]["workflow_reason"] == "max_retries_exceeded"
    with pytest.raises(WorkflowAdapterError):
        apply_run_result_to_graph(graph, "w_video", "done", artifact="x.mp4")


def test_apply_result_preserves_positions_and_done_artifact():
    graph = workflow_to_graph(
        _dag(), positions={"w_script": {"x": 3, "y": 4}}
    )
    new_graph = apply_run_result_to_graph(
        graph, "w_video", "done", artifact="fake/clip.mp4"
    )
    node = _by_id(new_graph)["w_video"]
    assert node["status"] == "completed"
    assert node["config"]["workflow_artifact"] == "fake/clip.mp4"
    assert _by_id(new_graph)["w_script"]["position"] == {"x": 3, "y": 4}
    assert new_graph["edges"] == graph["edges"]


def test_planned_graph_contains_only_rerun_scope():
    scoped = planned_graph(_dag(), ["w_video"])
    ids = [n["node_id"] for n in scoped["nodes"]]
    assert ids == ["w_script", "w_frame", "w_tail", "w_video"]
    assert all(
        e["from_node_id"] in ids and e["to_node_id"] in ids
        for e in scoped["edges"]
    )


# ── reuse seams: preflight + persistence payload ───────────────────────────

def test_preflight_reuse_reads_workflow_video_nodes():
    report = run_preflight_for_workflow(_dag())
    assert report.passed is True
    assert report.estimated_cost_usd == 0.0  # wan_local default is free
    over = run_preflight_for_workflow(_dag(), budget_usd=0.0)
    # All mapped video nodes here use the free default provider.
    assert over.passed is True


def test_graph_service_payload_shape():
    payload = as_graph_service_payload(
        workflow_to_graph(_dag()), name="Invented", description="d"
    )
    assert payload["name"] == "Invented"
    assert payload["description"] == "d"
    assert len(payload["nodes"]) == 7
    assert len(payload["edges"]) == 9
    # Payload is a copy: mutating it must not touch a fresh graph.
    payload["nodes"][0]["config"]["x"] = 1
    assert "x" not in _by_id(workflow_to_graph(_dag()))["w_script"]["config"]


def test_round_trip_is_not_mutated_by_conversion():
    workflow = _dag()
    snapshot = copy.deepcopy(workflow)
    workflow_to_graph(workflow)
    graph_to_workflow(workflow_to_graph(workflow))
    assert workflow == snapshot
