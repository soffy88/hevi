"""Tests for the open-source-canvas P0 grafts (clean-room, method only).

Covers the gateway contract, the model-install gate and the
canvas execution schedule. No network, no ComfyUI, no generation.
"""

import pytest

from hevi.capabilities.canvas_execution_schedule import (
    cancel_execution,
    expand_seed_batch,
    plan_canvas_execution,
    resolve_execution_results,
)
from hevi.capabilities.comfy_gateway_contract import (
    DEFAULT_MAX_BODY_BYTES,
    check_gateway_request,
    check_health_response,
)
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.model_install_gate import check_model_install
from hevi.capabilities.registry import get


def _nodes(*specs):
    return [
        {"node_id": node_id, "type": "script", "inputs": inputs}
        for node_id, inputs in specs
    ]


# --- gateway contract -------------------------------------------------

ALLOWED_CASES = [
    ("POST", "/prompt"),
    ("GET", "/history/abc123"),
    ("GET", "/view"),
    ("POST", "/upload/image"),
    ("POST", "/interrupt"),
    ("GET", "/system_stats"),
]


@pytest.mark.parametrize("method,path", ALLOWED_CASES)
def test_gateway_allows_the_six_endpoints(method, path):
    report = check_gateway_request({"method": method, "path": path})
    assert report["verdict"] == "pass"
    assert report["endpoint"] is not None


def test_gateway_denies_websocket_upgrade():
    report = check_gateway_request(
        {
            "method": "GET",
            "path": "/ws",
            "headers": {"upgrade": "websocket"},
        }
    )
    assert report["verdict"] == "fail"
    assert any(f["code"] == "websocket_denied" for f in report["failures"])


def test_gateway_denies_websocket_path_without_header():
    report = check_gateway_request({"method": "GET", "path": "/ws"})
    assert report["verdict"] == "fail"


def test_gateway_denies_free_and_object_info_and_install():
    for path in ("/free", "/object_info", "/object_info/CheckpointLoaderSimple", "/custom_nodes/install"):
        report = check_gateway_request({"method": "GET", "path": path})
        assert report["verdict"] == "fail", path
        assert any(
            f["code"] == "endpoint_not_allowed" for f in report["failures"]
        ), path


def test_gateway_denies_wrong_method_on_allowed_path():
    report = check_gateway_request({"method": "DELETE", "path": "/prompt"})
    assert report["verdict"] == "fail"


def test_gateway_body_cap_default_and_configurable():
    over = check_gateway_request(
        {"method": "POST", "path": "/prompt", "body_bytes": DEFAULT_MAX_BODY_BYTES + 1}
    )
    assert over["verdict"] == "fail"
    assert any(f["code"] == "body_too_large" for f in over["failures"])
    at_cap = check_gateway_request(
        {"method": "POST", "path": "/prompt", "body_bytes": DEFAULT_MAX_BODY_BYTES}
    )
    assert at_cap["verdict"] == "pass"
    small_cap = check_gateway_request(
        {"method": "POST", "path": "/prompt", "body_bytes": 11},
        max_body_bytes=10,
    )
    assert small_cap["verdict"] == "fail"


def test_gateway_cross_visitor_denied_and_same_visitor_allowed():
    denied = check_gateway_request(
        {
            "method": "GET",
            "path": "/history/abc",
            "visitor_id": "alice",
            "resource_visitor_id": "bob",
        }
    )
    assert denied["verdict"] == "fail"
    assert any(f["code"] == "cross_visitor_denied" for f in denied["failures"])
    anonymous = check_gateway_request(
        {"method": "GET", "path": "/view", "resource_visitor_id": "bob"}
    )
    assert anonymous["verdict"] == "fail"
    allowed = check_gateway_request(
        {
            "method": "GET",
            "path": "/view",
            "visitor_id": "alice",
            "resource_visitor_id": "alice",
        }
    )
    assert allowed["verdict"] == "pass"


def test_gateway_secret_values_and_unknown_layer_fail():
    secret = check_gateway_request(
        {
            "method": "GET",
            "path": "/system_stats",
            "auth_layer": "gateway_key",
            "osc_access_key": "hunter2",
        }
    )
    assert secret["verdict"] == "fail"
    assert any(
        f["code"] == "secret_must_not_be_supplied" for f in secret["failures"]
    )
    unknown = check_gateway_request(
        {"method": "GET", "path": "/system_stats", "auth_layer": "magic"}
    )
    assert unknown["verdict"] == "fail"
    declared = check_gateway_request(
        {"method": "GET", "path": "/system_stats", "auth_layer": "gateway_key"}
    )
    assert declared["verdict"] == "pass"


def test_gateway_malformed_request_raises():
    with pytest.raises(CapabilityError):
        check_gateway_request("not a dict")
    with pytest.raises(CapabilityError):
        check_gateway_request({"path": "/prompt"})


def test_health_response_redaction():
    redacted = check_health_response({"online": True, "version": "0.42.0"})
    assert redacted["verdict"] == "pass"
    leaked = check_health_response(
        {"online": True, "version": "0.42.0", "queue": [], "devices": ["cuda:0"]}
    )
    assert leaked["verdict"] == "fail"
    assert any(
        f["code"] == "health_response_not_redacted" for f in leaked["failures"]
    )
    authed = check_health_response(
        {"online": True, "version": "0.42.0", "queue": []}, authenticated=True
    )
    assert authed["verdict"] == "pass"


# --- model install gate ------------------------------------------------

MODEL = {
    "model_id": "ltx-video-2b",
    "install": [
        {
            "loader": "CheckpointLoaderSimple",
            "field": "ckpt_name",
            "folder": "checkpoints",
            "files": ["ltx-video-2b.safetensors"],
        },
        {
            "loader": "CLIPLoader",
            "field": "clip_name",
            "folder": "clip",
            "files": ["t5xxl.safetensors", "clip-l.safetensors"],
        },
    ],
}

SNAPSHOT = {
    "source": "local /object_info read",
    "loaders": {
        "CheckpointLoaderSimple": ["ltx-video-2b.safetensors"],
        "CLIPLoader": ["t5xxl.safetensors", "clip-l.safetensors"],
    },
}


def test_model_install_all_present_passes():
    report = check_model_install(MODEL, SNAPSHOT)
    assert report["verdict"] == "pass"
    assert report["missing"] == []
    assert report["checked_files"] == 3


def test_model_install_missing_file_names_file_and_folder():
    snapshot = {
        "loaders": {
            "CheckpointLoaderSimple": ["ltx-video-2b.safetensors"],
            "CLIPLoader": ["t5xxl.safetensors"],
        }
    }
    report = check_model_install(MODEL, snapshot)
    assert report["verdict"] == "fail"
    assert report["missing"] == [
        {
            "loader": "CLIPLoader",
            "field": "clip_name",
            "folder": "clip",
            "file": "clip-l.safetensors",
        }
    ]
    assert any(f["code"] == "model_file_missing" for f in report["failures"])


def test_model_install_missing_loader_fails():
    report = check_model_install(MODEL, {"loaders": {"CLIPLoader": []}})
    assert report["verdict"] == "fail"
    assert any(
        f["code"] == "loader_not_in_snapshot" for f in report["failures"]
    )


def test_model_install_missing_snapshot_fails_without_guessing():
    report = check_model_install(MODEL, None)
    assert report["verdict"] == "fail"
    assert any(f["code"] == "snapshot_missing" for f in report["failures"])
    assert report["checked_files"] == 0


def test_model_install_flat_snapshot_shape_and_extra_files_ok():
    flat = {
        "CheckpointLoaderSimple": ["ltx-video-2b.safetensors", "other.safetensors"],
        "CLIPLoader": ["t5xxl.safetensors", "clip-l.safetensors"],
    }
    report = check_model_install(MODEL, flat)
    assert report["verdict"] == "pass"


def test_model_install_malformed_model_raises():
    with pytest.raises(CapabilityError):
        check_model_install({"install": []}, SNAPSHOT)
    with pytest.raises(CapabilityError):
        check_model_install(MODEL, "not a snapshot")


# --- execution schedule ------------------------------------------------

def test_schedule_respects_dependencies_and_parallel_cap():
    workflow = {"nodes": _nodes(("a", []), ("b", ["a"]), ("c", ["a"]), ("d", ["b", "c"]))}
    plan = plan_canvas_execution(workflow, max_parallel=2)
    assert plan["verdict"] == "pass"
    assert [batch["node_ids"] for batch in plan["batches"]] == [["a"], ["b", "c"], ["d"]]


def test_schedule_chunks_ready_nodes_by_parallel_cap():
    workflow = {"nodes": _nodes(("a", []), ("b", []), ("c", []), ("d", ["a", "b", "c"]))}
    plan = plan_canvas_execution(workflow, max_parallel=2)
    assert [batch["node_ids"] for batch in plan["batches"]] == [
        ["a", "b"],
        ["c"],
        ["d"],
    ]


def test_schedule_upstream_failure_skips_downstream_transitively():
    workflow = {"nodes": _nodes(("a", []), ("b", ["a"]), ("c", ["b"]), ("d", []))}
    dispositions = resolve_execution_results(
        workflow, {"a": "failed", "d": "done"}
    )
    assert dispositions["a"]["disposition"] == "failed"
    assert dispositions["b"] == {
        "disposition": "skipped",
        "reason": "upstream_failed",
    }
    assert dispositions["c"] == {
        "disposition": "skipped",
        "reason": "upstream_failed",
    }
    assert dispositions["d"]["disposition"] == "done"


def test_schedule_unknown_result_node_raises():
    workflow = {"nodes": _nodes(("a", []))}
    with pytest.raises(CapabilityError):
        resolve_execution_results(workflow, {"zzz": "done"})


def test_schedule_retry_conflict_fails():
    workflow = {"nodes": _nodes(("a", []))}
    conflict = plan_canvas_execution(workflow, max_attempts=5)
    assert conflict["verdict"] == "fail"
    assert any(
        f["code"] == "retry_policy_conflict" for f in conflict["failures"]
    )
    node_conflict = plan_canvas_execution(
        {
            "nodes": [
                {
                    "node_id": "a",
                    "type": "script",
                    "inputs": [],
                    "params": {"max_retries": 1},
                }
            ]
        }
    )
    assert node_conflict["verdict"] == "fail"
    matching = plan_canvas_execution(workflow, max_attempts=3)
    assert matching["verdict"] == "pass"
    assert matching["max_attempts"] == 3


def test_schedule_seed_batches_expand_one_task_per_seed():
    workflow = {"nodes": _nodes(("a", []))}
    plan = plan_canvas_execution(
        workflow, seed_batches={"a": {"base_seed": 10, "count": 3}}
    )
    assert plan["verdict"] == "pass"
    assert [task["seed"] for task in plan["seed_tasks"]] == [10, 11, 12]
    assert plan["batches"][0]["tasks"] == [
        "a:seed:10",
        "a:seed:11",
        "a:seed:12",
    ]
    with pytest.raises(CapabilityError):
        expand_seed_batch("a", 10, 5)
    with pytest.raises(CapabilityError):
        expand_seed_batch("a", 10, 0)


def test_schedule_cancel_records_interrupt_without_performing():
    workflow = {"nodes": _nodes(("a", []), ("b", ["a"]))}
    plan = plan_canvas_execution(workflow)
    cancelled = cancel_execution(plan)
    assert cancelled["cancelled"] == ["a", "b"]
    assert cancelled["interrupt_action"] == "POST /interrupt"
    assert cancelled["performed"] is False


def test_schedule_cycle_rejected_by_workflow_validation():
    workflow = {"nodes": _nodes(("a", ["b"]), ("b", ["a"]))}
    with pytest.raises(CapabilityError):
        plan_canvas_execution(workflow)


# --- registration --------------------------------------------------------

def test_new_capabilities_registered():
    assert get("qa.comfy_gateway_contract").name == "qa.comfy_gateway_contract"
    assert get("qa.model_install_gate").name == "qa.model_install_gate"
    assert get("pipeline.canvas_execution_schedule").name == (
        "pipeline.canvas_execution_schedule"
    )
