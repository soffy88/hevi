"""Tests for the Toonflow recheck graft (A1-A3 gates, B1-B2 fake adapters).

Clean-room: only the mapping contract, the link discipline, and
the recovery discipline are judged here, plus the fake
execution adapters. No Toonflow code is imported, no generator
runs, no key or GPU is needed. Real execution waits on a
channel, a key, and a budget, and is not covered here.
"""

import hashlib

import pytest

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.reference_map_adapter import bind_references
from hevi.capabilities.reference_map_contract import check_reference_map
from hevi.capabilities.registry import get as registry_get
from hevi.capabilities.sandbox_material_reference_gate import (
    check_sandbox_material_references,
)
from hevi.capabilities.task_recovery_contract import (
    execute_recovery_fake,
    plan_recovery,
)
from hevi.capabilities.task_recovery_gate import check_task_recovery


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _codes(report: dict) -> list[str]:
    return [p["code"] for p in report["problems"]]


# --- A1: reference-map contract ---

def test_map_complete_mapping_passes_with_frame_kinds():
    report = check_reference_map(
        "Hero {{ref 1}} in front of {{ref 2}}, ending on {{ref 3}}",
        ["hero-pic", "street-pic", "hero-video"],
        [
            {"number": 1, "asset_id": "hero-pic", "kind": "first_frame"},
            {"number": 2, "asset_id": "street-pic"},
            {"number": 3, "asset_id": "hero-video", "kind": "last_frame"},
        ],
    )
    assert report["ok"] is True
    assert report["resolved"] == {
        1: "hero-pic",
        2: "street-pic",
        3: "hero-video",
    }
    assert report["frame_kinds"] == {
        1: "first_frame",
        2: "reference",
        3: "last_frame",
    }


def test_map_dict_form_defaults_to_reference_kind():
    report = check_reference_map(
        "Use {{ref 1}} and {{ref 2}}",
        ["a", "b"],
        {"1": "a", "2": "b"},
    )
    assert report["ok"] is True
    assert report["frame_kinds"] == {1: "reference", 2: "reference"}


def test_map_missing_mapping_fails_and_names_number():
    report = check_reference_map(
        "Use {{ref 1}} and {{ref 3}}",
        ["a", "b", "c"],
        [{"number": 1, "asset_id": "a"}],
    )
    assert report["ok"] is False
    assert "missing_mapping" in _codes(report)
    assert any(p.get("number") == 3 for p in report["problems"])


def test_map_undeclared_asset_fails():
    report = check_reference_map(
        "Use {{ref 1}}",
        ["a"],
        [{"number": 1, "asset_id": "ghost"}],
    )
    assert report["ok"] is False
    assert "mapping_asset_not_in_order" in _codes(report)


def test_map_unused_binding_fails():
    report = check_reference_map(
        "Use {{ref 1}}",
        ["a", "b"],
        [
            {"number": 1, "asset_id": "a"},
            {"number": 2, "asset_id": "b", "kind": "first_frame"},
        ],
    )
    assert report["ok"] is False
    assert "unused_frame_binding" in _codes(report)


def test_map_identity_first_convention_checked():
    report = check_reference_map(
        "Use {{ref 1}}",
        ["hero-pic", "street-pic"],
        [{"number": 1, "asset_id": "street-pic"}],
        numbering_convention="identity-first",
        identity_asset_id="hero-pic",
    )
    assert report["ok"] is False
    assert "identity_first_mismatch" in _codes(report)

    report = check_reference_map(
        "Use {{ref 1}}",
        ["hero-pic", "street-pic"],
        [{"number": 1, "asset_id": "hero-pic"}],
        numbering_convention="identity-first",
        identity_asset_id="hero-pic",
    )
    assert report["ok"] is True


def test_map_identity_first_without_identity_asset_fails():
    report = check_reference_map(
        "Use {{ref 1}}",
        ["hero-pic"],
        [{"number": 1, "asset_id": "hero-pic"}],
        numbering_convention="identity-first",
    )
    assert report["ok"] is False
    assert "missing_identity_asset" in _codes(report)


def test_map_unknown_convention_raises():
    with pytest.raises(CapabilityError):
        check_reference_map(
            "Use {{ref 1}}",
            ["a"],
            [{"number": 1, "asset_id": "a"}],
            numbering_convention="person-first",
        )


def test_map_duplicate_order_raises():
    with pytest.raises(CapabilityError):
        check_reference_map(
            "Use {{ref 1}}",
            ["a", "a"],
            [{"number": 1, "asset_id": "a"}],
        )


# --- A2: sandbox material references ---

_SCOPE = ["/data/sandbox/project-x"]


def test_sandbox_links_inside_scope_pass():
    report = check_sandbox_material_references(
        [
            {
                "material_id": "m1",
                "sha256": _sha("frame-a"),
                "path": "/data/sandbox/project-x/clips/a.png",
            },
            {
                "material_id": "m2",
                "sha256": _sha("frame-b"),
                "path": "clips/b.png",
            },
        ],
        declared_scope=_SCOPE,
    )
    assert report["ok"] is True
    assert report["checked"] == 2


def test_sandbox_relative_escape_fails():
    report = check_sandbox_material_references(
        [
            {
                "material_id": "m1",
                "sha256": _sha("frame-a"),
                "path": "../outside/a.png",
            },
        ],
        declared_scope=_SCOPE,
    )
    assert report["ok"] is False
    assert "scope_escape" in _codes(report)


def test_sandbox_absolute_escape_fails():
    report = check_sandbox_material_references(
        [
            {
                "material_id": "m1",
                "sha256": _sha("frame-a"),
                "path": "/etc/passwd",
            },
        ],
        declared_scope=_SCOPE,
    )
    assert report["ok"] is False
    assert "scope_escape" in _codes(report)


def test_sandbox_bad_sha_and_moved_fail():
    report = check_sandbox_material_references(
        [
            {
                "material_id": "m1",
                "sha256": "deadbeef",
                "path": "/data/sandbox/project-x/a.png",
                "moved": True,
            },
        ],
        declared_scope=_SCOPE,
    )
    assert report["ok"] is False
    assert "bad_sha256" in _codes(report)
    assert "material_moved" in _codes(report)


def test_sandbox_id_sha_conflict_fails():
    report = check_sandbox_material_references(
        [
            {
                "material_id": "m1",
                "sha256": _sha("one"),
                "path": "/data/sandbox/project-x/a.png",
            },
            {
                "material_id": "m1",
                "sha256": _sha("two"),
                "path": "/data/sandbox/project-x/b.png",
            },
        ],
        declared_scope=_SCOPE,
    )
    assert report["ok"] is False
    assert "material_id_sha_conflict" in _codes(report)


def test_sandbox_missing_scope_raises():
    with pytest.raises(CapabilityError):
        check_sandbox_material_references(
            [
                {
                    "material_id": "m1",
                    "sha256": _sha("x"),
                    "path": "/data/sandbox/project-x/a.png",
                },
            ],
            declared_scope=[],
        )


# --- A3: task recovery gate ---

def _plan(**overrides):
    plan = {
        "task_id": "task-1",
        "segments": ["s1", "s2", "s3", "s4"],
        "segments_to_run": ["s3", "s4"],
        "rerun_from_start": False,
    }
    plan.update(overrides)
    return plan


def _checkpoint(**overrides):
    record = {
        "task_id": "task-1",
        "state": "interrupted",
        "completed_segments": ["s1", "s2"],
        "position": "s3",
        "recorded_at": "2026-11-02T04:00:00+08:00",
    }
    record.update(overrides)
    return record


def test_recovery_valid_checkpoint_passes():
    report = check_task_recovery(_plan(), checkpoint=_checkpoint())
    assert report["ok"] is True
    assert report["completed_segments"] == ["s1", "s2"]


def test_recovery_missing_checkpoint_fails():
    report = check_task_recovery(_plan())
    assert report["ok"] is False
    assert "missing_checkpoint" in _codes(report)


def test_recovery_checkpoint_from_another_task_fails():
    report = check_task_recovery(
        _plan(), checkpoint=_checkpoint(task_id="task-9")
    )
    assert report["ok"] is False
    assert "checkpoint_task_mismatch" in _codes(report)


def test_recovery_completed_checkpoint_not_resumable():
    report = check_task_recovery(
        _plan(), checkpoint=_checkpoint(state="completed")
    )
    assert report["ok"] is False
    assert "checkpoint_not_resumable" in _codes(report)


def test_recovery_rerunning_completed_segment_fails():
    report = check_task_recovery(
        _plan(segments_to_run=["s2", "s3", "s4"]),
        checkpoint=_checkpoint(),
    )
    assert report["ok"] is False
    assert "reruns_completed_segment" in _codes(report)


def test_recovery_restart_claimed_as_recovery_fails():
    report = check_task_recovery(
        _plan(rerun_from_start=True),
        checkpoint=_checkpoint(),
    )
    assert report["ok"] is False
    assert "restart_claimed_as_recovery" in _codes(report)


def test_recovery_position_already_completed_fails():
    report = check_task_recovery(
        _plan(), checkpoint=_checkpoint(position="s2")
    )
    assert report["ok"] is False
    assert "checkpoint_position_completed" in _codes(report)


def test_recovery_undated_checkpoint_fails():
    record = _checkpoint()
    del record["recorded_at"]
    report = check_task_recovery(_plan(), checkpoint=record)
    assert report["ok"] is False
    assert "checkpoint_undated" in _codes(report)


def test_recovery_checkpoint_carried_inside_plan():
    plan = _plan(checkpoint=_checkpoint())
    report = check_task_recovery(plan)
    assert report["ok"] is True


# --- B1: reference-map adapter (fake) ---

def test_adapter_binds_and_records_shas():
    result = bind_references(
        "Hero {{ref 1}} ending on {{ref 2}}",
        ["hero-pic", "hero-video"],
        [
            {"number": 1, "asset_id": "hero-pic", "kind": "first_frame"},
            {"number": 2, "asset_id": "hero-video", "kind": "last_frame"},
        ],
        asset_shas={
            "hero-pic": _sha("hero-pic"),
            "hero-video": _sha("hero-video"),
        },
    )
    assert result["ok"] is True
    assert result["refs_bound"] == 2
    assert result["bindings"][0]["kind"] == "first_frame"
    assert result["bindings"][1]["sha256"] == _sha("hero-video")


def test_adapter_missing_mapping_throws():
    with pytest.raises(CapabilityError):
        bind_references(
            "Use {{ref 1}} and {{ref 2}}",
            ["a", "b"],
            [{"number": 1, "asset_id": "a"}],
        )


def test_adapter_frame_kind_mismatch_throws():
    with pytest.raises(CapabilityError):
        bind_references(
            "Use {{ref 1}}",
            ["hero-pic", "street-pic"],
            [{"number": 1, "asset_id": "street-pic"}],
            numbering_convention="identity-first",
            identity_asset_id="hero-pic",
        )


# --- B2: task recovery contract (fake) ---

def test_contract_plan_skips_completed_segments():
    recovery = plan_recovery(_plan(), checkpoint=_checkpoint())
    assert recovery["ok"] is True
    assert recovery["segments_to_run"] == ["s3", "s4"]
    assert recovery["skipped_completed"] == ["s1", "s2"]
    assert recovery["resume_from"] == "s3"


def test_contract_fake_run_never_reruns_completed():
    result = execute_recovery_fake(_plan(), checkpoint=_checkpoint())
    assert result["ok"] is True
    assert [r["segment"] for r in result["ran"]] == ["s3", "s4"]
    assert result["ran_count"] == 2
    assert result["skipped_completed"] == ["s1", "s2"]
    assert all(r["backend"] == "fake" for r in result["ran"])


def test_contract_without_checkpoint_throws():
    with pytest.raises(CapabilityError):
        plan_recovery(_plan())


# --- registration ---

def test_new_capabilities_registered():
    for name in (
        "qa.reference_map_contract",
        "qa.sandbox_material_reference_gate",
        "qa.task_recovery_gate",
        "video.reference_map_adapter",
        "qa.task_recovery_contract",
    ):
        assert registry_get(name).name == name
