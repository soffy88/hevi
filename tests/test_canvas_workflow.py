"""Tests for hevi.capabilities.canvas_workflow.

All fixtures are invented for this test file only: generic node ids,
placeholder params and placeholder artifact paths. No real plot,
character, or production material is reused here.
"""

from __future__ import annotations

import pytest

from hevi.capabilities.canvas_workflow import (
    apply_run_result,
    create_workflow,
    from_json,
    plan_rerun,
    rerun_selection,
    to_json,
)
from hevi.capabilities.errors import CapabilityError


def _dag():
    # script -> first_frame -> video -> assemble, plus an audio leaf
    # feeding assemble directly (diamond-free, invented fixtures).
    return create_workflow(
        [
            {"node_id": "n_script", "type": "script"},
            {
                "node_id": "n_frame",
                "type": "first_frame",
                "inputs": ["n_script"],
            },
            {
                "node_id": "n_video",
                "type": "video",
                "inputs": ["n_frame"],
                "params": {"duration_sec": 5},
            },
            {"node_id": "n_audio", "type": "audio", "inputs": ["n_script"]},
            {
                "node_id": "n_assemble",
                "type": "assemble",
                "inputs": ["n_video", "n_audio"],
            },
        ]
    )


def test_topo_order_dependency_before_dependent():
    order = rerun_selection(_dag(), ["n_assemble"])
    assert order.index("n_script") < order.index("n_frame")
    assert order.index("n_frame") < order.index("n_video")
    assert order.index("n_video") < order.index("n_assemble")
    assert order.index("n_audio") < order.index("n_assemble")
    assert len(order) == len(set(order)) == 5


def test_create_preserves_caller_order():
    workflow = _dag()
    assert [n["node_id"] for n in workflow["nodes"]] == [
        "n_script",
        "n_frame",
        "n_video",
        "n_audio",
        "n_assemble",
    ]


def test_create_fills_defaults():
    workflow = create_workflow([{"node_id": "only", "type": "script"}])
    node = workflow["nodes"][0]
    assert node["inputs"] == []
    assert node["params"] == {}
    assert node["status"] == "pending"
    assert node["artifact"] is None
    assert node["attempts"] == 0


def test_empty_nodes_raise():
    with pytest.raises(CapabilityError):
        create_workflow([])


def test_duplicate_node_id_raises():
    with pytest.raises(CapabilityError):
        create_workflow(
            [
                {"node_id": "dup", "type": "script"},
                {"node_id": "dup", "type": "video"},
            ]
        )


def test_invalid_type_raises():
    with pytest.raises(CapabilityError):
        create_workflow([{"node_id": "bad", "type": "render"}])


def test_unknown_input_raises():
    with pytest.raises(CapabilityError):
        create_workflow(
            [
                {"node_id": "a", "type": "script"},
                {"node_id": "b", "type": "video", "inputs": ["missing"]},
            ]
        )


def test_cycle_raises():
    with pytest.raises(CapabilityError):
        create_workflow(
            [
                {"node_id": "a", "type": "script", "inputs": ["b"]},
                {"node_id": "b", "type": "video", "inputs": ["a"]},
            ]
        )


def test_self_reference_raises():
    with pytest.raises(CapabilityError):
        create_workflow(
            [{"node_id": "a", "type": "script", "inputs": ["a"]}]
        )


def test_rerun_selection_unknown_selected_raises():
    with pytest.raises(CapabilityError):
        rerun_selection(_dag(), ["no_such_node"])


def test_rerun_selection_includes_unselected_upstream_no_duplicates():
    order = rerun_selection(_dag(), ["n_assemble", "n_video"])
    # Upstream nodes are pulled in even though only the leaf was picked.
    assert set(order) == {
        "n_script",
        "n_frame",
        "n_video",
        "n_audio",
        "n_assemble",
    }
    assert len(order) == len(set(order))
    assert order[-1] == "n_assemble"
    # Diamond-style overlap: selecting a node and its dependency
    # still emits each node once.
    order2 = rerun_selection(_dag(), ["n_video", "n_frame"])
    assert order2.count("n_frame") == 1
    assert order2.count("n_script") == 1
    assert order2.index("n_script") < order2.index("n_frame")


def test_plan_rerun_skips_done_with_artifact():
    workflow = _dag()
    workflow = apply_run_result(
        workflow, "n_script", "done", artifact="artifacts/script.txt"
    )
    workflow = apply_run_result(
        workflow, "n_frame", "done", artifact="artifacts/frame.png"
    )
    plan = plan_rerun(workflow, ["n_assemble"])
    by_id = {item["node_id"]: item for item in plan}
    assert by_id["n_script"] == {
        "node_id": "n_script",
        "action": "skip",
        "reason": "already_done",
    }
    assert by_id["n_frame"]["action"] == "skip"
    assert by_id["n_video"] == {
        "node_id": "n_video",
        "action": "run",
        "reason": "dependency",
    }
    assert by_id["n_assemble"]["reason"] == "selected"
    # Topological order is preserved in the plan.
    assert [item["node_id"] for item in plan] == rerun_selection(
        workflow, ["n_assemble"]
    )


def test_plan_rerun_explicitly_selected_done_not_skipped():
    workflow = _dag()
    workflow = apply_run_result(
        workflow, "n_script", "done", artifact="artifacts/script.txt"
    )
    plan = plan_rerun(workflow, ["n_script"])
    assert plan == [
        {"node_id": "n_script", "action": "run", "reason": "selected"}
    ]


def test_plan_rerun_done_without_artifact_is_not_skipped():
    workflow = _dag()
    workflow = apply_run_result(workflow, "n_script", "done")
    plan = plan_rerun(workflow, ["n_video"])
    by_id = {item["node_id"]: item for item in plan}
    assert by_id["n_script"]["action"] == "run"
    assert by_id["n_script"]["reason"] == "dependency"


def test_apply_done_updates_artifact_and_keeps_attempts():
    workflow = _dag()
    workflow = apply_run_result(
        workflow, "n_video", "failed", artifact=None
    )
    assert workflow["nodes"][2]["attempts"] == 1
    updated = apply_run_result(
        workflow, "n_video", "done", artifact="artifacts/clip.mp4"
    )
    node = updated["nodes"][2]
    assert node["status"] == "done"
    assert node["artifact"] == "artifacts/clip.mp4"
    assert node["attempts"] == 1


def test_apply_unknown_node_and_invalid_status_raise():
    workflow = _dag()
    with pytest.raises(CapabilityError):
        apply_run_result(workflow, "missing", "done")
    with pytest.raises(CapabilityError):
        apply_run_result(workflow, "n_script", "pending")
    with pytest.raises(CapabilityError):
        apply_run_result(workflow, "n_script", "blocked")


def test_retry_first_two_stay_failed():
    workflow = _dag()
    first = apply_run_result(workflow, "n_video", "failed")
    node = first["nodes"][2]
    assert node["status"] == "failed"
    assert node["attempts"] == 1
    second = apply_run_result(first, "n_video", "failed")
    node = second["nodes"][2]
    assert node["status"] == "failed"
    assert node["attempts"] == 2


def test_retry_third_blocks_and_further_call_raises():
    workflow = _dag()
    workflow = apply_run_result(workflow, "n_video", "failed")
    workflow = apply_run_result(workflow, "n_video", "failed")
    blocked = apply_run_result(workflow, "n_video", "failed")
    node = blocked["nodes"][2]
    assert node["status"] == "blocked"
    assert node["attempts"] == 3
    assert node["reason"] == "max_retries_exceeded"
    with pytest.raises(CapabilityError):
        apply_run_result(blocked, "n_video", "failed")
    with pytest.raises(CapabilityError):
        apply_run_result(blocked, "n_video", "done")


def test_apply_run_result_does_not_mutate_input():
    workflow = _dag()
    before = to_json(workflow)
    updated = apply_run_result(
        workflow, "n_video", "done", artifact="artifacts/clip.mp4"
    )
    assert to_json(workflow) == before
    assert workflow["nodes"][2]["status"] == "pending"
    assert workflow["nodes"][2]["artifact"] is None
    failed = apply_run_result(workflow, "n_video", "failed")
    assert workflow["nodes"][2]["attempts"] == 0
    assert failed["nodes"][2]["attempts"] == 1
    assert updated is not workflow


def test_to_json_from_json_roundtrip_deep_equal():
    workflow = _dag()
    workflow = apply_run_result(
        workflow, "n_script", "done", artifact="artifacts/script.txt"
    )
    text = to_json(workflow)
    restored = from_json(text)
    assert restored == workflow
    assert to_json(restored) == text


@pytest.mark.parametrize(
    "bad",
    [
        "not json at all",
        "{}",
        '{"nodes": []}',
        '{"nodes": [{"node_id": "a", "type": "nope"}]}',
        '{"nodes": [{"node_id": "a", "type": "script", "inputs": ["ghost"]}]}',
        '{"nodes": [{"node_id": "a", "type": "script", "inputs": ["a"]}]}',
        '{"nodes": [{"node_id": "a", "type": "script"}, '
        '{"node_id": "a", "type": "video"}]}',
        '{"nodes": "not a list"}',
        "[]",
    ],
)
def test_from_json_illegal_structure_raises(bad):
    with pytest.raises(CapabilityError):
        from_json(bad)
