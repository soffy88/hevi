"""Tests for the pixelaigc H3 workflow graft (A1-A3 + B1+B2).

Clean-room: only the configuration discipline, the frame
arithmetic, the staleness rule, the fake adapter shape, and the
equivalence protocol are judged here. No workflow file is read,
no example text is copied, no weights are touched, no ComfyUI
call is made, and no GPU is needed. Real runs wait on a GPU and
a ComfyUI install.
"""

import pytest

from hevi.capabilities import registry as registry_mod
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.h3_config_equivalence_protocol import (
    check_equivalence_protocol,
    equivalence_protocol,
)
from hevi.capabilities.h3_config_registration import (
    CONFIG_ID,
    COMPONENTS,
    config_record,
    check_h3_config,
)
from hevi.capabilities.h3_frame_align_gate import (
    aligned_frames,
    check_frame_alignment,
    requested_frames,
)
from hevi.capabilities.h3_single_segment_adapter import (
    SEGMENT_STAGES,
    build_execution_plan,
    execute_fake,
)
from hevi.capabilities.h3_stale_defaults_gate import check_stale_defaults


def _config_plan(**overrides):
    plan = {
        "config_id": CONFIG_ID,
        "components": dict(COMPONENTS),
        "lora_families": [],
        "source": "review",
        "source_date": "2026-11-03",
        "verified": False,
    }
    plan.update(overrides)
    return plan


# --- A1: configuration registration ---

def test_config_record_is_unverified_and_not_equivalent():
    record = config_record()
    assert record["config_id"] == CONFIG_ID
    assert record["verified"] is False
    assert record["not_equivalent_to"] == "fasth3-omniref-int8"
    assert record["weight_license"] == "unverified"


def test_config_gate_passes_for_registered_record():
    assert check_h3_config(_config_plan())["ok"]


def test_config_gate_rejects_lora_mix():
    report = check_h3_config(_config_plan(lora_families=["pika-h3-flex-turbo"]))
    assert not report["ok"]
    assert any(i["code"] == "lora_mix" for i in report["issues"])


def test_config_gate_rejects_verified_and_equivalence_claims():
    assert any(
        i["code"] == "verified_claim_without_run"
        for i in check_h3_config(_config_plan(verified=True))["issues"]
    )
    assert any(
        i["code"] == "equivalence_claim_without_evidence"
        for i in check_h3_config(
            _config_plan(equivalent_to="fasth3-omniref-int8")
        )["issues"]
    )


def test_config_gate_rejects_component_swap_and_missing_source():
    swapped = _config_plan()
    swapped["components"]["diffusion_model"] = "fasth3_omniref_8step_pruned_int8_convrot.safetensors"
    assert any(
        i["code"] == "component_mismatch"
        for i in check_h3_config(swapped)["issues"]
    )
    nosource = _config_plan(source="", source_date="")
    assert any(
        i["code"] == "source_undeclared"
        for i in check_h3_config(nosource)["issues"]
    )


def test_config_gate_rejects_defaulted_weight_license():
    report = check_h3_config(_config_plan(weight_license="MIT"))
    assert any(i["code"] == "weight_license_defaulted" for i in report["issues"])


# --- A2: frame alignment ---

def test_frame_arithmetic_examples():
    assert requested_frames(6.0) == 144
    assert aligned_frames(6.0) == 158
    assert aligned_frames(5.0) == 124
    assert aligned_frames(13.268) == 328


def test_frame_gate_passes_with_declared_stretch():
    report = check_frame_alignment(
        {"duration_s": 6.0, "frames": 158, "declared_output_s": 158 / 24}
    )
    assert report["ok"]
    assert report["alignment"]["expected_frames"] == 158


def test_frame_gate_rejects_snap_down_and_undeclared_stretch():
    down = check_frame_alignment({"duration_s": 6.0, "frames": 141})
    assert not down["ok"]
    assert any(i["code"] == "frame_count_off_grid" for i in down["issues"])
    undeclared = check_frame_alignment({"duration_s": 6.0, "frames": 158})
    assert any(
        i["code"] == "undeclared_output_stretch" for i in undeclared["issues"]
    )
    wrong_dir = check_frame_alignment(
        {
            "duration_s": 6.0,
            "frames": 158,
            "snap_direction": "down",
            "declared_output_s": 158 / 24,
        }
    )
    assert any(i["code"] == "snap_direction_not_up" for i in wrong_dir["issues"])


def test_frame_gate_rejects_output_mismatch():
    report = check_frame_alignment(
        {"duration_s": 6.0, "frames": 158, "declared_output_s": 6.0}
    )
    assert any(i["code"] == "output_duration_mismatch" for i in report["issues"])


# --- A3: stale inner defaults ---

def _stale_plan(**overrides):
    plan = {
        "outer_panel": {"resolution": "864x480", "frames": 158, "duration": 6},
        "inner_defaults": {"resolution": "1344x768", "frames": 73, "duration": 2},
        "effective": {"resolution": "864x480", "frames": 158, "duration": 6},
    }
    plan.update(overrides)
    return plan


def test_stale_gate_passes_for_clean_plan():
    assert check_stale_defaults(_stale_plan())["ok"]


def test_stale_gate_fails_when_effective_matches_inner_default():
    stale = _stale_plan(
        effective={"resolution": "1344x768", "frames": 158, "duration": 6}
    )
    report = check_stale_defaults(stale)
    assert not report["ok"]
    assert report["stale_fields"] == ["resolution"]
    assert any(i["code"] == "stale_inner_defaults" for i in report["issues"])


def test_stale_gate_fails_without_panel_or_inner_defaults():
    assert any(
        i["code"] == "outer_panel_undeclared"
        for i in check_stale_defaults({"inner_defaults": {}, "effective": {}})["issues"]
    )
    assert any(
        i["code"] == "inner_defaults_undeclared"
        for i in check_stale_defaults(_stale_plan(inner_defaults={}))["issues"]
    )


# --- B1: fake single-segment adapter ---

def _adapter_request(**overrides):
    request = {
        "mode": "first_last",
        "first_frame": True,
        "last_frame": True,
        "prompt_present": True,
        "config_id": CONFIG_ID,
        "duration_s": 6.0,
        "frames": 158,
        "declared_output_s": 158 / 24,
        "lora_families": [],
    }
    request.update(overrides)
    return request


def test_adapter_builds_fake_plan_with_stage_lists():
    plan = build_execution_plan(_adapter_request())
    assert plan["backend"] == "fake"
    assert plan["segment_stages"] == list(SEGMENT_STAGES)
    assert plan["audio_input"] is False
    assert plan["relay"] is False
    record = execute_fake(plan)
    assert record["backend"] == "fake"
    assert record["artifact"] is None
    assert record["stages_checked"] == len(plan["outer_stages"]) + len(
        plan["segment_stages"]
    )


def test_adapter_modes_and_missing_frames():
    assert build_execution_plan(_adapter_request(mode="first_only", last_frame=False))["mode"] == "first_only"
    assert build_execution_plan(
        _adapter_request(mode="text_only", first_frame=False, last_frame=False)
    )["mode"] == "text_only"
    with pytest.raises(CapabilityError, match="both a first frame"):
        build_execution_plan(_adapter_request(last_frame=False))
    with pytest.raises(CapabilityError, match="neither"):
        build_execution_plan(_adapter_request(mode="text_only"))


def test_adapter_rejects_lora_mix_and_off_grid_and_stale():
    with pytest.raises(CapabilityError, match="never be mixed"):
        build_execution_plan(
            _adapter_request(lora_families=["pika-h3-flex-turbo"])
        )
    with pytest.raises(CapabilityError, match="frame alignment"):
        build_execution_plan(_adapter_request(frames=144))
    with pytest.raises(CapabilityError, match="stale inner defaults"):
        build_execution_plan(
            _adapter_request(
                stale_defaults_plan=_stale_plan(
                    effective={"resolution": "1344x768", "frames": 158, "duration": 6}
                )
            )
        )


# --- B2: equivalence protocol ---

def test_protocol_template_is_not_run_and_unmeasured():
    protocol = equivalence_protocol()
    assert protocol["status"] == "not_run"
    assert protocol["comparison"]["raters"] == 5
    assert protocol["comparison"]["blind"] is True
    assert protocol["measured_fields"]["wall_time_s"] == "to_be_measured"
    assert protocol["measured_fields"]["peak_vram_mib"] == "to_be_measured"
    assert check_equivalence_protocol(protocol)["ok"]


def test_protocol_rejects_weak_or_executed_claims():
    weak = equivalence_protocol()
    weak["comparison"]["raters"] = 3
    weak["comparison"]["blind"] = False
    issues = check_equivalence_protocol(weak)["issues"]
    assert any(i["code"] == "too_few_raters" for i in issues)
    assert any(i["code"] == "comparison_not_blind" for i in issues)
    claimed = equivalence_protocol()
    claimed["equivalent"] = True
    assert any(
        i["code"] == "equivalence_claim_without_run"
        for i in check_equivalence_protocol(claimed)["issues"]
    )
    measured = equivalence_protocol()
    measured["measured_fields"]["wall_time_s"] = 42.0
    assert any(
        i["code"] == "measured_value_without_run"
        for i in check_equivalence_protocol(measured)["issues"]
    )


# --- registry ---

def test_capabilities_registered():
    for name in (
        "qa.h3_config_registration",
        "qa.h3_frame_align_gate",
        "qa.h3_stale_defaults_gate",
        "video.h3_single_segment_adapter",
        "qa.h3_config_equivalence_protocol",
    ):
        assert registry_mod.contains(name), name
