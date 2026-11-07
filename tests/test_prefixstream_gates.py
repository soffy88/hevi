"""Tests for the PrefixStream discipline gates (A1-A5).

Clean-room: only the grid rule (5+17k), the record discipline,
and the ledger rule are judged here. No plugin code is imported,
no generation runs, no GPU is needed. B1-B3 (execution) wait on
a GPU and a ComfyUI install and are not covered here.
"""

import hashlib

from hevi.capabilities.clip_lineage_schema import (
    check_clip_lineage,
    lineage_chain,
)
from hevi.capabilities.continuation_grid_gate import (
    check_continuation_grid,
    is_on_grid,
    snap_down,
    snap_up,
)
from hevi.capabilities.continuation_source_gate import (
    check_continuation_source,
)
from hevi.capabilities.degradation_ledger import check_degradation_ledger
from hevi.capabilities.disk_stream_gate import check_disk_stream_plan


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --- A1: continuation grid ---

def test_grid_membership_and_snaps():
    assert is_on_grid(5)
    assert is_on_grid(22)
    assert is_on_grid(124)
    assert is_on_grid(192)
    assert is_on_grid(328)
    assert not is_on_grid(318)
    assert not is_on_grid(240)
    assert not is_on_grid(4)
    assert snap_down(318) == 311
    assert snap_up(318) == 328
    assert snap_down(328) == 328
    assert snap_up(328) == 328


def test_grid_h3_route_328_passes():
    report = check_continuation_grid(
        {"route": "h3", "segments": [{"frames": 328}, {"frames": 124}]}
    )
    assert report["ok"]
    assert report["issues"] == []


def test_grid_fasth3_318_fails_with_neighbours():
    report = check_continuation_grid(
        {"route": "fasth3", "segments": [{"frames": 318}]}
    )
    assert not report["ok"]
    issue = report["issues"][0]
    assert issue["code"] == "off_grid"
    assert issue["snap_down"] == 311
    assert issue["snap_up"] == 328
    assert "fasth3" in issue["detail"]


def test_grid_execution_crop_fails():
    report = check_continuation_grid(
        {
            "route": "h3",
            "segments": [{"frames": 328, "execution_crop": True}],
        }
    )
    assert not report["ok"]
    assert report["issues"][0]["code"] == "execution_crop"


def test_grid_route_must_be_declared_and_separate():
    report = check_continuation_grid({"segments": [{"frames": 124}]})
    assert not report["ok"]
    assert any(i["code"] == "route_undeclared" for i in report["issues"])
    report = check_continuation_grid(
        {"route": "fasth3", "segments": [{"frames": "124"}]}
    )
    assert not report["ok"]
    assert any(i["code"] == "frames_not_integer" for i in report["issues"])


def test_grid_declared_snap_passes():
    report = check_continuation_grid(
        {
            "route": "fasth3",
            "segments": [{"frames": 328, "snapped": True, "snapped_from": 318}],
        }
    )
    assert report["ok"]


# --- A2: continuation source ---

def _source_plan(second_source=None):
    segments = [{"clip_id": "clip-1"}]
    second = {"clip_id": "clip-2"}
    if second_source is not None:
        second["context_source"] = second_source
    segments.append(second)
    return {"segments": segments}


def test_source_fresh_start_and_real_source_pass():
    report = check_continuation_source(
        _source_plan(
            {
                "source_clip_id": "clip-1",
                "source_sha256": _sha("clip-1"),
                "kind": "latent_tail",
            }
        )
    )
    assert report["ok"]


def test_source_missing_fails():
    report = check_continuation_source(_source_plan())
    assert not report["ok"]
    assert report["issues"][0]["code"] == "context_source_missing"


def test_source_placeholder_and_zero_sha_fail():
    report = check_continuation_source(
        _source_plan(
            {
                "source_clip_id": "placeholder-clip",
                "source_sha256": "0" * 64,
                "kind": "last_frame",
            }
        )
    )
    assert not report["ok"]
    codes = {i["code"] for i in report["issues"]}
    assert "source_clip_id_placeholder" in codes
    assert "source_sha256_zero" in codes


def test_source_malformed_sha_and_kind_fail():
    report = check_continuation_source(
        _source_plan(
            {
                "source_clip_id": "clip-1",
                "source_sha256": "not-a-hash",
                "kind": "kv_cache",
            }
        )
    )
    assert not report["ok"]
    codes = {i["code"] for i in report["issues"]}
    assert "source_sha256_malformed" in codes
    assert "source_kind_unknown" in codes


def test_source_tags_field_and_auto_reference_fail():
    plan = _source_plan(
        {
            "source_clip_id": "clip-1",
            "source_sha256": _sha("clip-1"),
            "kind": "multi_frame_ref",
            "tags": ["heroine"],
        }
    )
    plan["segments"][1]["auto_reference_from_generated"] = True
    plan["segments"][1]["tags"] = ["heroine"]
    report = check_continuation_source(plan)
    assert not report["ok"]
    codes = {i["code"] for i in report["issues"]}
    assert "tags_field_unimplemented" in codes
    assert "auto_reference_from_generated" in codes


def test_source_self_reference_fails():
    report = check_continuation_source(
        _source_plan(
            {
                "source_clip_id": "clip-2",
                "source_sha256": _sha("clip-2"),
                "kind": "latent_tail",
            }
        )
    )
    assert not report["ok"]
    assert any(i["code"] == "source_is_self" for i in report["issues"])


# --- A3: clip lineage schema ---

def _records():
    return [
        {
            "clip_id": "clip-1",
            "prompt": "heroine in the pavilion",
            "rating": 4,
            "rating_source": "manual",
            "shape": {"frames": 124, "width": 768, "height": 768, "fps": 24},
            "parent_clip_id": None,
        },
        {
            "clip_id": "clip-2",
            "prompt": "heroine turns",
            "rating": 5,
            "rating_source": "manual",
            "shape": {"frames": 124, "width": 768, "height": 768, "fps": 24},
            "parent_clip_id": "clip-1",
            "branch": "alternate-ending",
            "branch_from": "clip-1",
            "branch_semantics": "dag_selection",
        },
        {
            "clip_id": "clip-3",
            "prompt": "heroine turns, second take",
            "rating": 3,
            "rating_source": "manual",
            "shape": {"frames": 124, "width": 768, "height": 768, "fps": 24},
            "parent_clip_id": "clip-2",
        },
    ]


def test_lineage_three_generation_chain_passes():
    records = _records()
    assert lineage_chain(records, "clip-3") == ["clip-3", "clip-2", "clip-1"]
    report = check_clip_lineage(records)
    assert report["ok"]
    assert report["records"][2]["chain"] == ["clip-3", "clip-2", "clip-1"]


def test_lineage_auto_rating_fails():
    records = _records()
    records[0]["rating_source"] = "auto"
    report = check_clip_lineage(records)
    assert not report["ok"]
    assert any(i["code"] == "rating_not_manual" for i in report["issues"])


def test_lineage_missing_rating_source_fails():
    records = _records()
    del records[0]["rating_source"]
    report = check_clip_lineage(records)
    assert not report["ok"]
    assert any(i["code"] == "rating_source_missing" for i in report["issues"])


def test_lineage_version_fork_semantics_fail():
    records = _records()
    records[1]["branch_semantics"] = "version_fork"
    report = check_clip_lineage(records)
    assert not report["ok"]
    assert any(
        i["code"] == "branch_semantics_not_dag" for i in report["issues"]
    )


def test_lineage_unknown_parent_and_cycle_fail():
    records = _records()
    records[1]["parent_clip_id"] = "clip-9"
    report = check_clip_lineage(records)
    assert not report["ok"]
    assert any(
        i["code"] == "parent_clip_id_unknown" for i in report["issues"]
    )
    records = _records()
    records[0]["parent_clip_id"] = "clip-3"
    report = check_clip_lineage(records)
    assert not report["ok"]
    assert any(i["code"] == "lineage_cycle" for i in report["issues"])


def test_lineage_rating_range_and_shape_fail():
    records = _records()
    records[0]["rating"] = 6
    records[1]["shape"]["fps"] = 0
    report = check_clip_lineage(records)
    assert not report["ok"]
    codes = {i["code"] for i in report["issues"]}
    assert "rating_out_of_range" in codes
    assert "shape_field_invalid" in codes


# --- A4: disk stream ---

def _disk_plan(**overrides):
    plan = {
        "output_mode": "disk_stream",
        "manifest": True,
        "concat": {"mode": "copy"},
        "in_memory_all_frames": False,
        "seam_handling": "stitcher",
        "geometry": {
            "fps": 24,
            "width": 768,
            "height": 768,
            "sample_rate": 24000,
            "channels": 2,
        },
        "segments": [
            {
                "geometry": {
                    "fps": 24,
                    "width": 768,
                    "height": 768,
                    "sample_rate": 24000,
                    "channels": 2,
                },
                "on_mismatch": "reject",
            }
        ],
    }
    plan.update(overrides)
    return plan


def test_disk_stream_valid_plan_passes():
    report = check_disk_stream_plan(_disk_plan())
    assert report["ok"]


def test_disk_stream_geometry_mismatch_must_reject():
    plan = _disk_plan()
    plan["segments"][0]["geometry"]["width"] = 512
    plan["segments"][0]["on_mismatch"] = "append"
    report = check_disk_stream_plan(plan)
    assert not report["ok"]
    assert any(
        i["code"] == "geometry_mismatch_not_rejected"
        for i in report["issues"]
    )
    plan["segments"][0]["on_mismatch"] = "reject"
    assert check_disk_stream_plan(plan)["ok"]


def test_disk_stream_memory_hold_fails():
    report = check_disk_stream_plan(
        _disk_plan(in_memory_all_frames=True, manifest=False)
    )
    assert not report["ok"]
    codes = {i["code"] for i in report["issues"]}
    assert "all_frames_in_memory" in codes
    assert "manifest_missing" in codes


def test_disk_stream_seam_claim_fails():
    report = check_disk_stream_plan(_disk_plan(seam_handling="disk_stream"))
    assert not report["ok"]
    assert any(
        i["code"] == "seam_claimed_by_disk_stream"
        for i in report["issues"]
    )
    assert check_disk_stream_plan(
        _disk_plan(seam_handling="hard_cut_declared")
    )["ok"]


# --- A5: degradation ledger ---

def _ledger(**overrides):
    segments = [
        {
            "order": 1,
            "context_source": None,
            "degradation_observation": {"notes": "baseline segment"},
        },
        {
            "order": 2,
            "context_source": {
                "source_clip_id": "clip-1",
                "source_sha256": _sha("clip-1"),
            },
            "degradation_observation": {
                "notes": "no visible drift in the pavilion lattice"
            },
        },
    ]
    ledger = {"segments": segments}
    ledger.update(overrides)
    return ledger


def test_ledger_complete_passes():
    report = check_degradation_ledger(_ledger())
    assert report["verdict"] == "pass"
    assert report["ok"]


def test_ledger_unfilled_observation_is_not_checked():
    ledger = _ledger()
    ledger["segments"][1]["degradation_observation"] = {"notes": "  "}
    report = check_degradation_ledger(ledger)
    assert report["verdict"] == "not_checked"
    assert report["ok"]  # not_checked is not a failure
    assert report["not_checked"][0]["code"] == (
        "degradation_observation_unfilled"
    )


def test_ledger_verified_experiment_fails():
    ledger = _ledger()
    ledger["segments"][1]["experimental_means"] = [
        {"name": "soft_mask", "verified": True}
    ]
    report = check_degradation_ledger(ledger)
    assert report["verdict"] == "fail"
    assert any(
        i["code"] == "unverified_means_claimed_verified"
        for i in report["issues"]
    )


def test_ledger_experiment_in_default_plan_fails():
    ledger = _ledger()
    ledger["segments"][1]["experimental_means"] = [
        {"name": "anti_burn_lora", "verified": False, "in_default_plan": True}
    ]
    report = check_degradation_ledger(ledger)
    assert report["verdict"] == "fail"
    assert any(
        i["code"] == "experimental_means_in_default_plan"
        for i in report["issues"]
    )


def test_ledger_order_and_source_rules_fail():
    ledger = _ledger()
    ledger["segments"][1]["order"] = 3
    ledger["segments"][1]["context_source"] = None
    report = check_degradation_ledger(ledger)
    assert report["verdict"] == "fail"
    codes = {i["code"] for i in report["issues"]}
    assert "order_not_consecutive" in codes
    assert "context_source_missing" in codes
