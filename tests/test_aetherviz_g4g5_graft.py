"""Tests for the aetherviz G4/G5 graft.

Every capability gets a positive case and at least one
negative case. The registration test asserts all ten names
are present exactly once. The schema (B) tests assert
fail-closed behaviour: ``compile_*`` returns a contract
declaring ``executed_here`` false and ``output_file`` None on
a well-formed input, and raises ``CapabilityError`` on any
shape violation. No test renders, calls a paid API, loads a
model, or touches the network. The A3 theme test covers 25
themes plus boundary cases.
"""

from __future__ import annotations

import json

import pytest

from hevi.capabilities import list_capabilities
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.gsap_timeline_honesty_gate import check_gsap_timeline_honesty
from hevi.capabilities.hybrid_render_mode_gate import (
    check_hybrid_render_mode,
    derive_mode,
)
from hevi.capabilities.hybrid_scene_sync_schema import compile_hybrid_scene_sync
from hevi.capabilities.hyperframes_composition_schema import (
    compile_hyperframes_composition,
)
from hevi.capabilities.paid_generation_cost_gate import check_paid_generation_cost
from hevi.capabilities.preview_to_video_pipeline_schema import (
    compile_preview_to_video_pipeline,
)
from hevi.capabilities.preview_video_five_segment_gate import (
    check_preview_video_five_segment,
)
from hevi.capabilities.slider_dual_channel_gate import check_slider_dual_channel
from hevi.capabilities.svg3d_overlay_schema import compile_svg3d_overlay
from hevi.capabilities.svg3d_projection_sync_gate import check_svg3d_projection_sync

EXPECTED_AETHERVIZ_G4G5_NAMES = {
    "qa.svg3d_projection_sync_gate",
    "qa.slider_dual_channel_gate",
    "qa.hybrid_render_mode_gate",
    "qa.preview_video_five_segment_gate",
    "qa.gsap_timeline_honesty_gate",
    "qa.paid_generation_cost_gate",
    "video.svg3d_overlay_schema",
    "video.hybrid_scene_sync_schema",
    "video.preview_to_video_pipeline_schema",
    "video.hyperframes_composition_schema",
}


def test_all_aetherviz_g4g5_names_registered():
    found = [c.name for c in list_capabilities() if c.name in EXPECTED_AETHERVIZ_G4G5_NAMES]
    assert sorted(found) == sorted(EXPECTED_AETHERVIZ_G4G5_NAMES)


def test_registered_names_unique():
    names = [c.name for c in list_capabilities()]
    assert len(names) == len(set(names))


# ---- A1 projection sync gate ----

_IDENTITY = [
    [1.0, 0.0, 0.0, 0.0],
    [0.0, 1.0, 0.0, 0.0],
    [0.0, 0.0, 1.0, 0.0],
    [0.0, 0.0, 0.0, 1.0],
]

_SCALE2 = [
    [2.0, 0.0, 0.0, 0.0],
    [0.0, 2.0, 0.0, 0.0],
    [0.0, 0.0, 1.0, 0.0],
    [0.0, 0.0, 0.0, 1.0],
]

_BEHIND = [
    [1.0, 0.0, 0.0, 0.0],
    [0.0, 1.0, 0.0, 0.0],
    [0.0, 0.0, 1.0, 0.0],
    [0.0, 0.0, 0.0, -1.0],
]


def _good_projection() -> dict:
    return {
        "point": [0.0, 0.0, 0.0],
        "view_projection": _IDENTITY,
        "viewport": {"width": 800, "height": 600},
        "dpr": 1.0,
        "screen": [400.0, 300.0],
    }


def test_projection_pass_identity():
    report = check_svg3d_projection_sync(_good_projection())
    assert report["verdict"] == "pass"
    assert report["executed_here"] is False
    assert report["ndc"] == [0.0, 0.0, 0.0]
    assert report["screen"] == [400.0, 300.0]


def test_projection_pass_scaled_and_resized():
    plan = {
        "point": [0.25, 0.25, 0.0],
        "view_projection": _SCALE2,
        "viewport": {"width": 800, "height": 600},
        "dpr": 2.0,
        "screen": [600.0, 150.0],
        "resize": {
            "viewport": {"width": 400, "height": 300},
            "screen": [300.0, 75.0],
        },
    }
    report = check_svg3d_projection_sync(plan)
    assert report["verdict"] == "pass"
    assert report["screen"] == [600.0, 150.0]


def test_projection_rejects_behind_camera():
    plan = _good_projection()
    plan["view_projection"] = _BEHIND
    report = check_svg3d_projection_sync(plan)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "behind_camera"


def test_projection_rejects_out_of_frustum():
    plan = _good_projection()
    plan["point"] = [2.0, 0.0, 0.0]
    report = check_svg3d_projection_sync(plan)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "out_of_frustum"


def test_projection_rejects_screen_mismatch():
    plan = _good_projection()
    plan["screen"] = [0.0, 0.0]
    report = check_svg3d_projection_sync(plan)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "screen_mismatch"


def test_projection_rejects_undeclared_dpr():
    plan = _good_projection()
    del plan["dpr"]
    report = check_svg3d_projection_sync(plan)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "dpr_undeclared"


def test_projection_rejects_undefined_point():
    plan = _good_projection()
    del plan["point"]
    report = check_svg3d_projection_sync(plan)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "point_undefined"


def test_projection_rejects_bad_matrix():
    plan = _good_projection()
    plan["view_projection"] = [[1.0, 0.0], [0.0, 1.0]]
    report = check_svg3d_projection_sync(plan)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "matrix_undefined"


def test_projection_rejects_zero_viewport():
    plan = _good_projection()
    plan["viewport"] = {"width": 0, "height": 600}
    report = check_svg3d_projection_sync(plan)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "viewport_undefined"


def test_projection_rejects_resize_mismatch():
    plan = {
        "point": [0.25, 0.25, 0.0],
        "view_projection": _SCALE2,
        "viewport": {"width": 800, "height": 600},
        "dpr": 1.0,
        "screen": [600.0, 150.0],
        "resize": {
            "viewport": {"width": 400, "height": 300},
            "screen": [999.0, 999.0],
        },
    }
    report = check_svg3d_projection_sync(plan)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "resize_mismatch"


def test_projection_rejects_non_object():
    report = check_svg3d_projection_sync("not a plan")
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "plan_not_object"


# ---- A2 slider dual-channel gate ----


def _good_slider() -> dict:
    return {
        "slider_value": 0.5,
        "source_of_truth": "slider",
        "updates": [
            {"channel": "object3d", "property": "rotation.y", "value": 0.5, "frame": 12},
            {"channel": "svg", "property": "d", "value": 0.5, "frame": 12},
        ],
    }


def test_slider_pass():
    report = check_slider_dual_channel(_good_slider())
    assert report["verdict"] == "pass"
    assert report["executed_here"] is False
    assert report["frame"] == 12


def test_slider_rejects_split_source():
    plan = _good_slider()
    plan["source_of_truth"] = "object3d"
    report = check_slider_dual_channel(plan)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "source_not_single"


def test_slider_rejects_missing_channel():
    plan = _good_slider()
    plan["updates"] = [plan["updates"][1]]
    report = check_slider_dual_channel(plan)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "channel_missing"


def test_slider_rejects_value_mismatch():
    plan = _good_slider()
    plan["updates"][1]["value"] = 0.6
    report = check_slider_dual_channel(plan)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "channel_value_mismatch"


def test_slider_rejects_channel_lag():
    plan = _good_slider()
    plan["updates"][1]["frame"] = 13
    report = check_slider_dual_channel(plan)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "channel_lag"


def test_slider_rejects_duplicate_channel():
    plan = _good_slider()
    plan["updates"].append({"channel": "svg", "property": "d", "value": 0.5, "frame": 12})
    report = check_slider_dual_channel(plan)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "channel_duplicate"


# ---- A3 hybrid render mode gate ----

THEME_CASES = [
    ("3D 旋转的地球模型", "three"),
    ("three.js scene with camera orbit", "three"),
    ("立体透视网格", "three"),
    ("3D model render", "three"),
    ("相机视角切换", "three"),
    ("速度矢量箭头标注", "svg"),
    ("label the velocity vector", "svg"),
    ("SVG 覆盖层标签", "svg"),
    ("注释与标签说明", "svg"),
    ("3D 场景中的速度矢量标注", "hybrid"),
    ("旋转模型上的 label", "hybrid"),
    ("three.js scene with vector overlay", "hybrid"),
    ("立体透视加箭头标注", "hybrid"),
    ("camera orbit with SVG labels", "hybrid"),
    ("模型渲染与矢量箭头", "hybrid"),
    ("牛顿第一定律", "three"),
    ("自由落体", "three"),
    ("a lesson about gravity", "three"),
    ("", "three"),
    ("3D", "three"),
    ("SVG", "svg"),
    ("LABEL", "svg"),
    ("3D LABEL", "hybrid"),
    ("网格与注释", "hybrid"),
    ("中英混合 3D scene 标注 label", "hybrid"),
]


@pytest.mark.parametrize("theme,mode", THEME_CASES)
def test_hybrid_mode_derives_from_theme(theme, mode):
    assert derive_mode(theme) == mode
    plan = {"theme": theme, "mode": mode}
    report = check_hybrid_render_mode(plan)
    assert report["verdict"] == "pass"
    assert report["mode"] == mode


def test_hybrid_mode_rejects_mismatch():
    plan = {"theme": "3D 旋转的地球模型", "mode": "hybrid"}
    report = check_hybrid_render_mode(plan)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "mode_mismatch"


def test_hybrid_mode_rejects_unknown_mode():
    plan = {"theme": "3D 旋转的地球模型", "mode": "2d"}
    report = check_hybrid_render_mode(plan)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "mode_unknown"


def test_hybrid_mode_accepts_atlas_palettes():
    plan = {
        "theme": "3D 场景中的速度矢量标注",
        "mode": "hybrid",
        "vector_colors": {"force": "red", "velocity": "blue", "acceleration": "ink"},
    }
    report = check_hybrid_render_mode(plan)
    assert report["verdict"] == "pass"


def test_hybrid_mode_rejects_green_palette():
    plan = {
        "theme": "3D 场景中的速度矢量标注",
        "mode": "hybrid",
        "vector_colors": {"acceleration": "green"},
    }
    report = check_hybrid_render_mode(plan)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "color_not_atlas_palette"


def test_hybrid_mode_rejects_hex_colour():
    plan = {
        "theme": "3D 场景中的速度矢量标注",
        "mode": "hybrid",
        "vector_colors": {"force": "#EF4444"},
    }
    report = check_hybrid_render_mode(plan)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "color_not_atlas_palette"


def test_hybrid_mode_rejects_wrong_role_palette():
    plan = {
        "theme": "3D 场景中的速度矢量标注",
        "mode": "hybrid",
        "vector_colors": {"velocity": "red"},
    }
    report = check_hybrid_render_mode(plan)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "color_role_mismatch"


# ---- A4 preview-to-video five-segment gate ----


def _good_five_segment() -> dict:
    return {
        "composition_id": "main",
        "segments": [
            {"id": "intro", "duration_s": 30},
            {"id": "ch1", "duration_s": 60},
            {"id": "ch2", "duration_s": 60},
            {"id": "ch3", "duration_s": 60},
            {"id": "outro", "duration_s": 30},
        ],
        "timeline": {"single": True, "mount": "window.__timelines['main']"},
        "video": {"autoplay": True, "interactive_controls": []},
        "teaching_line": False,
    }


def test_five_segment_pass():
    report = check_preview_video_five_segment(_good_five_segment())
    assert report["verdict"] == "pass"
    assert report["executed_here"] is False
    assert report["total_duration_s"] == 240
    assert report["segment_count"] == 5


def test_five_segment_pass_teaching_with_ledger():
    plan = _good_five_segment()
    plan["teaching_line"] = True
    plan["provenance"] = {
        "gate": "qa.source_sentence_ledger",
        "source_ledger_passed": True,
    }
    report = check_preview_video_five_segment(plan)
    assert report["verdict"] == "pass"


def test_five_segment_rejects_wrong_count():
    plan = _good_five_segment()
    plan["segments"] = plan["segments"][:4]
    report = check_preview_video_five_segment(plan)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "segment_count_wrong"


def test_five_segment_rejects_wrong_duration():
    plan = _good_five_segment()
    plan["segments"][4]["duration_s"] = 25
    report = check_preview_video_five_segment(plan)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "segment_duration_wrong"


def test_five_segment_rejects_missing_composition_id():
    plan = _good_five_segment()
    plan["composition_id"] = ""
    report = check_preview_video_five_segment(plan)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "composition_id_missing"


def test_five_segment_rejects_second_timeline():
    plan = _good_five_segment()
    plan["timeline"] = {"single": False, "mount": "window.__timelines['main']"}
    report = check_preview_video_five_segment(plan)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "timeline_not_single"


def test_five_segment_rejects_wrong_mount():
    plan = _good_five_segment()
    plan["timeline"] = {"single": True, "mount": "window.__timelines['other']"}
    report = check_preview_video_five_segment(plan)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "timeline_mount_wrong"


def test_five_segment_rejects_interactive_control():
    plan = _good_five_segment()
    plan["video"] = {"autoplay": True, "interactive_controls": ["slider"]}
    report = check_preview_video_five_segment(plan)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "interactive_control_in_video"


def test_five_segment_rejects_orbit_controls():
    plan = _good_five_segment()
    plan["video"] = {"autoplay": True, "interactive_controls": ["OrbitControls"]}
    report = check_preview_video_five_segment(plan)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "interactive_control_in_video"


def test_five_segment_rejects_autoplay_off():
    plan = _good_five_segment()
    plan["video"] = {"autoplay": False, "interactive_controls": []}
    report = check_preview_video_five_segment(plan)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "autoplay_off"


def test_five_segment_rejects_teaching_without_provenance():
    plan = _good_five_segment()
    plan["teaching_line"] = True
    report = check_preview_video_five_segment(plan)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "teaching_provenance_missing"


def test_five_segment_rejects_wrong_provenance_gate_name():
    # There is no citation_check capability in hevi; citing it fails.
    plan = _good_five_segment()
    plan["teaching_line"] = True
    plan["provenance"] = {"gate": "citation_check", "source_ledger_passed": True}
    report = check_preview_video_five_segment(plan)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "teaching_provenance_missing"


# ---- A5 GSAP timeline honesty gate ----


def _good_timeline() -> dict:
    return {
        "timeline_count": 1,
        "paused": True,
        "on_update_renders": True,
        "gsap_source": "method_only",
        "tweens": [],
    }


def test_gsap_timeline_pass():
    report = check_gsap_timeline_honesty(_good_timeline())
    assert report["verdict"] == "pass"
    assert report["executed_here"] is False


def test_gsap_timeline_pass_with_from_to():
    plan = _good_timeline()
    plan["tweens"] = [
        {
            "element": "title",
            "css_transform_present": True,
            "uses_from_to": True,
            "keeps_x_percent": True,
            "keeps_y_percent": True,
            "gsap_position_anim": False,
        }
    ]
    report = check_gsap_timeline_honesty(plan)
    assert report["verdict"] == "pass"


def test_gsap_timeline_rejects_second_timeline():
    plan = _good_timeline()
    plan["timeline_count"] = 2
    report = check_gsap_timeline_honesty(plan)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "timeline_count_wrong"


def test_gsap_timeline_rejects_unpaused():
    plan = _good_timeline()
    plan["paused"] = False
    report = check_gsap_timeline_honesty(plan)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "timeline_not_paused"


def test_gsap_timeline_rejects_missing_on_update():
    plan = _good_timeline()
    plan["on_update_renders"] = False
    report = check_gsap_timeline_honesty(plan)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "on_update_missing"


def test_gsap_timeline_rejects_transform_mix():
    plan = _good_timeline()
    plan["tweens"] = [
        {
            "element": "title",
            "css_transform_present": True,
            "uses_from_to": False,
            "keeps_x_percent": False,
            "keeps_y_percent": False,
            "gsap_position_anim": True,
        }
    ]
    report = check_gsap_timeline_honesty(plan)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "transform_mix"


def test_gsap_timeline_rejects_dropped_percent():
    plan = _good_timeline()
    plan["tweens"] = [
        {
            "element": "title",
            "css_transform_present": True,
            "uses_from_to": True,
            "keeps_x_percent": True,
            "keeps_y_percent": False,
            "gsap_position_anim": False,
        }
    ]
    report = check_gsap_timeline_honesty(plan)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "percent_lost"


def test_gsap_timeline_rejects_mit_label():
    plan = _good_timeline()
    plan["gsap_source"] = "mit"
    report = check_gsap_timeline_honesty(plan)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "gsap_license_mislabelled"


# ---- A6 paid generation cost gate ----


def _good_paid_call() -> dict:
    return {
        "model": "claude-sonnet-4-6",
        "max_tokens": 16000,
        "calls": 2,
        "input_tokens": 2000,
        "output_tokens": 10000,
        "estimated_cost_usd": 0.32,
        "budget_declared": True,
        "budget_usd": 0.50,
        "hyperframes_version": "0.1.0",
        "anthropic_key_connected": True,
    }


def test_paid_cost_pass():
    report = check_paid_generation_cost(_good_paid_call())
    assert report["verdict"] == "pass"
    assert report["executed_here"] is False
    assert report["cost_floor_usd"] == 0.312
    assert report["cost_cap_usd"] == 0.50


def test_paid_cost_rejects_undeclared_model():
    plan = _good_paid_call()
    plan["model"] = ""
    report = check_paid_generation_cost(plan)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "model_undeclared"


def test_paid_cost_rejects_undeclared_max_tokens():
    plan = _good_paid_call()
    del plan["max_tokens"]
    report = check_paid_generation_cost(plan)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "max_tokens_undeclared"


def test_paid_cost_rejects_undeclared_cost():
    plan = _good_paid_call()
    del plan["estimated_cost_usd"]
    report = check_paid_generation_cost(plan)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "cost_undeclared"


def test_paid_cost_rejects_undeclared_budget():
    plan = _good_paid_call()
    plan["budget_declared"] = False
    report = check_paid_generation_cost(plan)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "budget_undeclared"


def test_paid_cost_rejects_over_budget():
    plan = _good_paid_call()
    plan["budget_usd"] = 0.30
    report = check_paid_generation_cost(plan)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "cost_over_budget"


def test_paid_cost_rejects_over_cap():
    plan = _good_paid_call()
    plan["estimated_cost_usd"] = 0.60
    plan["budget_usd"] = 1.00
    report = check_paid_generation_cost(plan)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "cost_over_cap"


def test_paid_cost_rejects_understated():
    plan = _good_paid_call()
    plan["estimated_cost_usd"] = 0.10
    report = check_paid_generation_cost(plan)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "cost_understated"


def test_paid_cost_rejects_unpinned_hyperframes():
    plan = _good_paid_call()
    plan["hyperframes_version"] = ""
    report = check_paid_generation_cost(plan)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "hyperframes_version_unpinned"


def test_paid_cost_rejects_missing_key():
    plan = _good_paid_call()
    plan["anthropic_key_connected"] = False
    report = check_paid_generation_cost(plan)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "anthropic_key_missing"


def test_paid_cost_rejects_output_over_max():
    plan = _good_paid_call()
    plan["output_tokens"] = 20000
    report = check_paid_generation_cost(plan)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "output_tokens_over_max"


# ---- B1 svg3d overlay schema ----


def _good_overlay() -> dict:
    return {
        "anchors": [{"label": "速度", "point": [0.0, 5.0, 0.0]}],
        "view_box": {"width": 800, "height": 600},
        "pointer_events": "none",
    }


def test_overlay_schema_pass():
    contract = compile_svg3d_overlay(_good_overlay())
    assert contract["executed_here"] is False
    assert contract["output_file"] is None
    assert contract["contract"] == "svg3d-overlay"
    assert contract["pointer_events"] == "none"
    assert contract["anchors"][0]["label"] == "速度"


def test_overlay_schema_pass_string_view_box():
    plan = _good_overlay()
    plan["view_box"] = "0 0 800 600"
    contract = compile_svg3d_overlay(plan)
    assert contract["view_box"] == {"width": 800.0, "height": 600.0}


def test_overlay_schema_rejects_empty_anchors():
    plan = _good_overlay()
    plan["anchors"] = []
    with pytest.raises(CapabilityError):
        compile_svg3d_overlay(plan)


def test_overlay_schema_rejects_unlabelled_anchor():
    plan = _good_overlay()
    plan["anchors"] = [{"point": [0.0, 5.0, 0.0]}]
    with pytest.raises(CapabilityError):
        compile_svg3d_overlay(plan)


def test_overlay_schema_rejects_bad_point():
    plan = _good_overlay()
    plan["anchors"] = [{"label": "速度", "point": [0.0, 5.0]}]
    with pytest.raises(CapabilityError):
        compile_svg3d_overlay(plan)


def test_overlay_schema_rejects_missing_view_box():
    plan = _good_overlay()
    del plan["view_box"]
    with pytest.raises(CapabilityError):
        compile_svg3d_overlay(plan)


def test_overlay_schema_rejects_pointer_events():
    plan = _good_overlay()
    plan["pointer_events"] = "auto"
    with pytest.raises(CapabilityError):
        compile_svg3d_overlay(plan)


def test_overlay_schema_rejects_executed_claim():
    plan = _good_overlay()
    plan["executed_here"] = True
    with pytest.raises(CapabilityError):
        compile_svg3d_overlay(plan)


# ---- B2 hybrid scene sync schema ----


def _good_sync() -> dict:
    return {
        "three_scene": {"id": "projectile"},
        "svg_layer": {"id": "labels"},
        "sync_table": [
            {"point_id": "v0", "anchor_id": "label-v0"},
            {"point_id": "grav", "anchor_id": "label-grav"},
        ],
    }


def test_sync_schema_pass():
    contract = compile_hybrid_scene_sync(_good_sync())
    assert contract["executed_here"] is False
    assert contract["output_file"] is None
    assert contract["contract"] == "hybrid-scene-sync"
    assert contract["sync_entries"] == 2
    assert contract["three_scene_id"] == "projectile"


def test_sync_schema_rejects_missing_scene_id():
    plan = _good_sync()
    plan["three_scene"] = {}
    with pytest.raises(CapabilityError):
        compile_hybrid_scene_sync(plan)


def test_sync_schema_rejects_empty_table():
    plan = _good_sync()
    plan["sync_table"] = []
    with pytest.raises(CapabilityError):
        compile_hybrid_scene_sync(plan)


def test_sync_schema_rejects_entry_without_anchor():
    plan = _good_sync()
    plan["sync_table"] = [{"point_id": "v0"}]
    with pytest.raises(CapabilityError):
        compile_hybrid_scene_sync(plan)


def test_sync_schema_rejects_executed_claim():
    plan = _good_sync()
    plan["executed_here"] = True
    with pytest.raises(CapabilityError):
        compile_hybrid_scene_sync(plan)


# ---- B3 preview-to-video pipeline schema ----


def _good_pipeline() -> dict:
    return {
        "topic": "自由落体",
        "interactive_html": {"present": True},
        "video_html": {"present": True},
        "mp4": {"present": True},
        "cost_estimate_usd": 0.32,
        "hyperframes_version": "0.1.0",
    }


def test_pipeline_schema_pass():
    contract = compile_preview_to_video_pipeline(_good_pipeline())
    assert contract["executed_here"] is False
    assert contract["output_file"] is None
    assert contract["contract"] == "preview-to-video-pipeline"
    assert contract["stages"] == ["topic", "interactive_html", "video_html", "mp4"]


def test_pipeline_schema_rejects_missing_topic():
    plan = _good_pipeline()
    plan["topic"] = ""
    with pytest.raises(CapabilityError):
        compile_preview_to_video_pipeline(plan)


def test_pipeline_schema_rejects_missing_stage():
    plan = _good_pipeline()
    plan["video_html"] = {"present": False}
    with pytest.raises(CapabilityError):
        compile_preview_to_video_pipeline(plan)


def test_pipeline_schema_rejects_cost_over_cap():
    plan = _good_pipeline()
    plan["cost_estimate_usd"] = 0.60
    with pytest.raises(CapabilityError):
        compile_preview_to_video_pipeline(plan)


def test_pipeline_schema_rejects_unpinned_hyperframes():
    plan = _good_pipeline()
    plan["hyperframes_version"] = ""
    with pytest.raises(CapabilityError):
        compile_preview_to_video_pipeline(plan)


def test_pipeline_schema_rejects_executed_claim():
    plan = _good_pipeline()
    plan["executed_here"] = True
    with pytest.raises(CapabilityError):
        compile_preview_to_video_pipeline(plan)


# ---- B4 hyperframes composition schema ----


def _good_composition() -> dict:
    return {
        "composition_id": "main",
        "duration_s": 240,
        "tracks": [
            {"id": "video", "kind": "gsap"},
            {"id": "audio", "kind": "narration"},
        ],
        "timelines_mount": "window.__timelines['main']",
        "segments": [
            {"id": "intro", "duration_s": 30},
            {"id": "ch1", "duration_s": 60},
            {"id": "ch2", "duration_s": 60},
            {"id": "ch3", "duration_s": 60},
            {"id": "outro", "duration_s": 30},
        ],
    }


def test_composition_schema_pass():
    contract = compile_hyperframes_composition(_good_composition())
    assert contract["executed_here"] is False
    assert contract["output_file"] is None
    assert contract["contract"] == "hyperframes-composition"
    assert contract["tracks"] == ["video", "audio"]
    assert contract["timelines_mount"] == "window.__timelines['main']"


def test_composition_schema_rejects_missing_id():
    plan = _good_composition()
    plan["composition_id"] = ""
    with pytest.raises(CapabilityError):
        compile_hyperframes_composition(plan)


def test_composition_schema_rejects_zero_duration():
    plan = _good_composition()
    plan["duration_s"] = 0
    with pytest.raises(CapabilityError):
        compile_hyperframes_composition(plan)


def test_composition_schema_rejects_empty_tracks():
    plan = _good_composition()
    plan["tracks"] = []
    with pytest.raises(CapabilityError):
        compile_hyperframes_composition(plan)


def test_composition_schema_rejects_track_without_kind():
    plan = _good_composition()
    plan["tracks"] = [{"id": "video"}]
    with pytest.raises(CapabilityError):
        compile_hyperframes_composition(plan)


def test_composition_schema_rejects_wrong_mount():
    plan = _good_composition()
    plan["timelines_mount"] = "window.__timelines['other']"
    with pytest.raises(CapabilityError):
        compile_hyperframes_composition(plan)


def test_composition_schema_rejects_segment_sum_mismatch():
    plan = _good_composition()
    plan["segments"] = plan["segments"][:4]
    with pytest.raises(CapabilityError):
        compile_hyperframes_composition(plan)


def test_composition_schema_rejects_executed_claim():
    plan = _good_composition()
    plan["executed_here"] = True
    with pytest.raises(CapabilityError):
        compile_hyperframes_composition(plan)


# ---- render smoke: _render writes a report JSON ----


def test_gate_render_writes_report(tmp_path):
    cap = next(c for c in list_capabilities() if c.name == "qa.svg3d_projection_sync_gate")
    result = cap.render(
        {"plan": _good_projection()},
        tmp_path,
        duration=0.0,
        aspect="16:9",
        seed=1,
    )
    report_path = tmp_path / "svg3d_projection_sync_report.json"
    assert report_path.exists()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["verdict"] == "pass"
    assert result.qa["verdict"] == "pass"


def test_schema_render_writes_contract(tmp_path):
    cap = next(c for c in list_capabilities() if c.name == "video.svg3d_overlay_schema")
    result = cap.render(
        {"plan": _good_overlay()},
        tmp_path,
        duration=0.0,
        aspect="16:9",
        seed=1,
    )
    contract_path = tmp_path / "svg3d_overlay_contract.json"
    assert contract_path.exists()
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    assert contract["executed_here"] is False
    assert contract["output_file"] is None
    assert result.qa["executed_here"] is False
