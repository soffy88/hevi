"""Tests for the claude-animation-skills graft (A1-A6 gates, B1-B2 fake schemas)."""

import pytest

from hevi.capabilities import (
    cartoon_rig_schema as b2,
)
from hevi.capabilities import (
    code_animation_caption_band_gate as a6,
)
from hevi.capabilities import (
    exploded_view_label_gate as a5,
)
from hevi.capabilities import (
    exploded_view_schema as b1,
)
from hevi.capabilities import (
    graph_honesty_gate as a2,
)
from hevi.capabilities import (
    ig_safe_area_profile as a1,
)
from hevi.capabilities import (
    map_honesty_gate as a3,
)
from hevi.capabilities import (
    whatif_script_format_gate as a4,
)
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import contains


def _ig_plan(**overrides):
    plan = {
        "profile": "ig_safe_9x16",
        "canvas": {"width": 1080, "height": 1920},
        "elements": [
            {"kind": "caption", "box": [100, 1500 - 80, 980, 1500]},
        ],
    }
    plan.update(overrides)
    return plan


def test_a1_pass_and_outside_element_fails():
    assert a1.check_ig_safe_area(_ig_plan())["verdict"] == "pass"
    bad = a1.check_ig_safe_area(
        _ig_plan(elements=[{"kind": "caption", "box": [50, 300, 980, 400]}])
    )
    assert bad["verdict"] == "fail"
    assert any(i["code"].endswith("outside_profile") for i in bad["issues"])


def test_a1_generic_margin_and_wrong_canvas_fail():
    assert a1.check_ig_safe_area(_ig_plan(profile="generic_48px"))["verdict"] == "fail"
    assert a1.check_ig_safe_area(_ig_plan(profile=None))["verdict"] == "fail"
    assert (
        a1.check_ig_safe_area(
            _ig_plan(canvas={"width": 1920, "height": 1080})
        )["verdict"]
        == "fail"
    )
    assert a1.check_ig_safe_area(_ig_plan(elements=[]))["verdict"] == "fail"


def test_a2_pass_and_invented_data_fails():
    good = {"values": [10, 20, 35], "labels": ["a", "b", "c"],
            "final": 35, "data_source": "monthly report"}
    assert a2.check_graph_honesty(good)["verdict"] == "pass"
    assert a2.check_graph_honesty({**good, "data_source": ""})["verdict"] == "fail"
    assert a2.check_graph_honesty({**good, "labels": ["a", "b"]})["verdict"] == "fail"
    assert a2.check_graph_honesty({**good, "final": 34})["verdict"] == "fail"
    assert a2.check_graph_honesty({**good, "values": [10, -5]})["verdict"] == "fail"


def test_a2_two_point_interpolated_curve_needs_schematic():
    plan = {"values": [10, 35], "labels": ["a", "b"], "final": 35,
            "data_source": "report", "curve_claim": "interpolated"}
    assert a2.check_graph_honesty(plan)["verdict"] == "fail"
    assert (
        a2.check_graph_honesty({**plan, "schematic_declared": True})["verdict"]
        == "pass"
    )


def test_a3_schematic_and_real_paths():
    schematic = {"map_kind": "schematic", "route_source": "procedural",
                 "schematic_declared": True,
                 "stops": [{"name": "home"}, {"name": "gym"}],
                 "eta_minutes": 9, "distance_km": 2.8, "eta_basis": "estimated"}
    assert a3.check_map_honesty(schematic)["verdict"] == "pass"
    assert a3.check_map_honesty({**schematic, "route_source": "osm"})["verdict"] == "fail"
    assert a3.check_map_honesty({**schematic, "schematic_declared": False})["verdict"] == "fail"
    assert a3.check_map_honesty(
        {**schematic, "stops": [{"name": "home", "real_place": True}]}
    )["verdict"] == "fail"
    real = {"map_kind": "real", "route_source": "osm", "eta_basis": "measured",
            "stops": [{"name": "Beijing", "lat": 39.9, "lon": 116.4}]}
    assert a3.check_map_honesty(real)["verdict"] == "pass"
    assert a3.check_map_honesty(
        {**real, "stops": [{"name": "Beijing"}]}
    )["verdict"] == "fail"


def _script_plan(**overrides):
    beats = ["hook", "misconception", "but_turn", "examples", "mechanism", "closing"]
    plan = {"sections": [{"kind": kind, "text": f"text for {kind}"} for kind in beats],
            "fact_checked": True}
    plan.update(overrides)
    return plan


def test_a4_pass_and_sequence_and_fact_rules():
    assert a4.check_whatif_script(_script_plan())["verdict"] == "pass"
    swapped = _script_plan()
    swapped["sections"][1], swapped["sections"][2] = swapped["sections"][2], swapped["sections"][1]
    assert a4.check_whatif_script(swapped)["verdict"] == "fail"
    assert a4.check_whatif_script(_script_plan(fact_checked=False))["verdict"] == "fail"
    assert (
        a4.check_whatif_script(
            _script_plan(theory_claims=True, hedging_present=False)
        )["verdict"]
        == "fail"
    )
    assert (
        a4.check_whatif_script(
            _script_plan(theory_claims=True, hedging_present=True)
        )["verdict"]
        == "pass"
    )
    assert a4.check_whatif_script(_script_plan(affiliation_claimed=True))["verdict"] == "fail"


def _layers_plan(**overrides):
    plan = {
        "flat_layered_object": True,
        "layers": [
            {"order": 1, "name": "glass", "note": "top layer",
             "anchor": {"x": 540, "y": 300}, "leader_line": True},
            {"order": 2, "name": "battery", "note": "power cell",
             "anchor": {"x": 540, "y": 600}, "leader_line": True},
        ],
    }
    plan.update(overrides)
    return plan


def test_a5_pass_and_label_rules():
    assert a5.check_exploded_view_labels(_layers_plan())["verdict"] == "pass"
    assert a5.check_exploded_view_labels(_layers_plan(flat_layered_object=False))["verdict"] == "fail"
    too_many = _layers_plan(layers=[
        {"order": i + 1, "name": f"l{i}", "note": "n",
         "anchor": {"x": 1, "y": 1}, "leader_line": True} for i in range(7)
    ])
    assert a5.check_exploded_view_labels(too_many)["verdict"] == "fail"
    bad_order = _layers_plan(layers=[
        {"order": 2, "name": "glass", "note": "top layer",
         "anchor": {"x": 540, "y": 300}, "leader_line": True},
    ])
    assert a5.check_exploded_view_labels(bad_order)["verdict"] == "fail"
    long_name = _layers_plan(layers=[
        {"order": 1, "name": "x" * 17, "note": "n",
         "anchor": {"x": 1, "y": 1}, "leader_line": True},
    ])
    assert a5.check_exploded_view_labels(long_name)["verdict"] == "fail"


def _band_plan(**overrides):
    plan = {
        "canvas": {"width": 1080, "height": 1920},
        "caption_band": {"box": [100, 1300, 980, 1420]},
        "elements": [{"kind": "face", "box": [400, 400, 680, 700]}],
        "word_timing_aligned": True,
    }
    plan.update(overrides)
    return plan


def test_a6_pass_and_band_rules():
    assert a6.check_caption_band(_band_plan())["verdict"] == "pass"
    overlap = _band_plan(elements=[{"kind": "face", "box": [400, 1350, 680, 1500]}])
    assert a6.check_caption_band(overlap)["verdict"] == "fail"
    outside = _band_plan(caption_band={"box": [100, 100, 980, 200]})
    assert a6.check_caption_band(outside)["verdict"] == "fail"
    assert a6.check_caption_band(_band_plan(word_timing_aligned=False))["verdict"] == "fail"
    stale = _band_plan(narration_changed=True, retimed_on_narration_change=False)
    assert a6.check_caption_band(stale)["verdict"] == "fail"
    retimed = _band_plan(narration_changed=True, retimed_on_narration_change=True)
    assert a6.check_caption_band(retimed)["verdict"] == "pass"


def _exploded_plan():
    return {"flat_layered_object": True, "object_kind": "flat device",
            "layers": _layers_plan()["layers"]}


def test_b1_contract_fake_and_errors():
    contract = b1.compile_exploded_view_contract(_exploded_plan())
    assert contract["executed_here"] is False
    assert contract["rendered_here"] is False
    assert contract["output_file"] is None
    assert contract["layer_count"] == 2
    assert [layer["order"] for layer in contract["layers"]] == [1, 2]
    with pytest.raises(CapabilityError):
        b1.compile_exploded_view_contract(
            {"flat_layered_object": False, "object_kind": "ball", "layers": []}
        )
    with pytest.raises(CapabilityError):
        b1.compile_exploded_view_contract(_exploded_plan() | {"layers": []})


def _rig_plan(**overrides):
    plan = {
        "rig": {"joints": ["pelvis", "spine", "chest", "neck", "head",
                           "arm_l", "arm_r", "leg_l", "leg_r"],
                "arms_ik": "two_bone"},
        "update_rule": "time_only",
        "poses": [{"name": "stand", "joints": {"pelvis": 0, "head": 0}}],
        "props": ["shield"],
        "mouth_control": True,
    }
    plan.update(overrides)
    return plan


def test_b2_contract_fake_and_errors():
    contract = b2.compile_cartoon_rig_contract(_rig_plan())
    assert contract["executed_here"] is False
    assert contract["rendered_here"] is False
    assert contract["output_file"] is None
    assert contract["pose_count"] == 1
    assert contract["update_rule"] == "time_only"
    with pytest.raises(CapabilityError):
        b2.compile_cartoon_rig_contract(_rig_plan(update_rule="stateful"))
    with pytest.raises(CapabilityError):
        b2.compile_cartoon_rig_contract(_rig_plan(affiliation_claimed=True))
    bad_rig = _rig_plan()
    bad_rig["rig"] = {"joints": ["pelvis", "spine"], "arms_ik": "two_bone"}
    with pytest.raises(CapabilityError):
        b2.compile_cartoon_rig_contract(bad_rig)
    bad_pose = _rig_plan(poses=[{"name": "x", "joints": {"wing": 1}}])
    with pytest.raises(CapabilityError):
        b2.compile_cartoon_rig_contract(bad_pose)


def test_all_eight_capabilities_registered():
    for name in (
        "qa.ig_safe_area_profile",
        "qa.graph_honesty_gate",
        "qa.map_honesty_gate",
        "qa.whatif_script_format_gate",
        "qa.exploded_view_label_gate",
        "qa.code_animation_caption_band_gate",
        "video.exploded_view_schema",
        "video.cartoon_rig_schema",
    ):
        assert contains(name), name
