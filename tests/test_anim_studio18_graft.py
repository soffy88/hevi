"""Animation studio 18 graft tests (A1-A6 gates, B1-B6 fake schemas).

The gate (A) tests assert pass/fail verdicts on good and bad
inputs. The schema (B) tests assert fail-closed behaviour:
``compile_*`` returns a contract declaring ``executed_here``
false and ``output_file`` None on a well-formed input, and
raises ``CapabilityError`` on any shape violation. The
registration test asserts all 12 new capability names are
present exactly once. No test runs Motion Canvas, Motion,
Ola, Two.js, gifenc, or Konva, loads weights, or touches a
GPU.
"""

from __future__ import annotations

import pytest

from hevi.capabilities import list_capabilities
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.gifenc_gif_export_gate import check_gifenc_gif_export
from hevi.capabilities.gifenc_gif_export_task_schema import (
    compile_gifenc_gif_export_task,
)
from hevi.capabilities.konva_interactive_stage_gate import (
    check_konva_interactive_stage,
)
from hevi.capabilities.konva_interactive_stage_task_schema import (
    compile_konva_interactive_stage_task,
)
from hevi.capabilities.motion_canvas_explainer_gate import (
    check_motion_canvas_explainer,
)
from hevi.capabilities.motion_canvas_explainer_task_schema import (
    compile_motion_canvas_explainer_task,
)
from hevi.capabilities.motion_layout_gesture_gate import (
    check_motion_layout_gesture,
)
from hevi.capabilities.motion_layout_transition_task_schema import (
    compile_motion_layout_transition_task,
)
from hevi.capabilities.ola_interpolation_task_schema import (
    compile_ola_interpolation_task,
)
from hevi.capabilities.ola_smooth_interpolation_gate import (
    check_ola_smooth_interpolation,
)
from hevi.capabilities.twojs_vector_scene_gate import check_twojs_vector_scene
from hevi.capabilities.twojs_vector_scene_task_schema import (
    compile_twojs_vector_scene_task,
)

NEW_NAMES = [
    "qa.motion_canvas_explainer_gate",
    "qa.motion_layout_gesture_gate",
    "qa.ola_smooth_interpolation_gate",
    "qa.twojs_vector_scene_gate",
    "qa.gifenc_gif_export_gate",
    "qa.konva_interactive_stage_gate",
    "video.motion_canvas_explainer_task_schema",
    "video.motion_layout_transition_task_schema",
    "video.ola_interpolation_task_schema",
    "video.twojs_vector_scene_task_schema",
    "video.gifenc_gif_export_task_schema",
    "video.konva_interactive_stage_task_schema",
]


def test_registration_names_present_exactly_once():
    names = [c.name for c in list_capabilities()]
    for name in NEW_NAMES:
        assert names.count(name) == 1, name


def _explainer_plan(**overrides):
    plan = {
        "scenes": [
            {"id": "intro", "duration_s": 30},
            {"id": "demo", "duration_s": 60},
        ],
        "total_seconds": 90,
        "audio_sync": True,
        "captions": True,
        "word_caption_alignment": True,
        "division_of_labour": "motion_canvas owns the explainer, manim owns the math proofs",
    }
    plan.update(overrides)
    return plan


def test_a1_explainer_pass():
    assert check_motion_canvas_explainer(_explainer_plan())["verdict"] == "pass"


def test_a1_explainer_empty_scenes_fail():
    assert check_motion_canvas_explainer(_explainer_plan(scenes=[]))["verdict"] == "fail"


def test_a1_explainer_durations_do_not_sum_fail():
    assert check_motion_canvas_explainer(_explainer_plan(total_seconds=100))["verdict"] == "fail"


def test_a1_explainer_captions_without_alignment_fail():
    plan = _explainer_plan()
    del plan["word_caption_alignment"]
    assert check_motion_canvas_explainer(plan)["verdict"] == "fail"


def test_a1_explainer_division_without_known_line_fail():
    plan = _explainer_plan(division_of_labour="the other tool owns everything")
    assert check_motion_canvas_explainer(plan)["verdict"] == "fail"


def test_a1_explainer_not_object_fail():
    assert check_motion_canvas_explainer("nope")["verdict"] == "fail"


def _layout_plan(**overrides):
    plan = {
        "transitions": [
            {
                "element": "card",
                "kind": "layout",
                "duration_s": 0.4,
                "layout_before": {"x": 0, "y": 0},
                "layout_after": {"x": 120, "y": 0},
            },
            {
                "element": "card",
                "kind": "gesture",
                "duration_s": 0.3,
                "start_state": {"scale": 1.0},
                "end_state": {"scale": 1.1},
            },
        ]
    }
    plan.update(overrides)
    return plan


def test_a2_layout_gesture_pass():
    assert check_motion_layout_gesture(_layout_plan())["verdict"] == "pass"


def test_a2_layout_gesture_tween_out_of_scope_fail():
    plan = _layout_plan(
        transitions=[
            {
                "element": "card",
                "kind": "tween",
                "duration_s": 0.4,
            }
        ]
    )
    verdict = check_motion_layout_gesture(plan)
    assert verdict["verdict"] == "fail"
    assert verdict["issues"][0]["code"] == "kind_out_of_scope"


def test_a2_layout_gesture_missing_layout_state_fail():
    plan = _layout_plan(
        transitions=[
            {
                "element": "card",
                "kind": "layout",
                "duration_s": 0.4,
                "layout_before": {"x": 0},
            }
        ]
    )
    assert check_motion_layout_gesture(plan)["verdict"] == "fail"


def test_a2_layout_gesture_missing_gesture_state_fail():
    plan = _layout_plan(
        transitions=[
            {
                "element": "card",
                "kind": "gesture",
                "duration_s": 0.3,
                "start_state": {"scale": 1.0},
            }
        ]
    )
    assert check_motion_layout_gesture(plan)["verdict"] == "fail"


def test_a2_layout_gesture_empty_fail():
    assert check_motion_layout_gesture({"transitions": []})["verdict"] == "fail"


def _ola_plan(**overrides):
    plan = {
        "streams": [
            {
                "name": "score",
                "rate": 0.2,
                "settle_seconds": 1.5,
                "max_jump": 10,
                "samples": [0, 5, 9, 12],
            }
        ]
    }
    plan.update(overrides)
    return plan


def test_a3_ola_pass():
    assert check_ola_smooth_interpolation(_ola_plan())["verdict"] == "pass"


def test_a3_ola_undeclared_jump_fail():
    plan = _ola_plan(
        streams=[
            {
                "name": "score",
                "rate": 0.2,
                "settle_seconds": 1.5,
                "max_jump": 10,
                "samples": [0, 5, 40],
            }
        ]
    )
    verdict = check_ola_smooth_interpolation(plan)
    assert verdict["verdict"] == "fail"
    assert verdict["issues"][0]["code"] == "jump_without_declaration"


def test_a3_ola_declared_jump_pass():
    plan = _ola_plan(
        streams=[
            {
                "name": "score",
                "rate": 0.2,
                "settle_seconds": 1.5,
                "max_jump": 10,
                "declared_jump": True,
                "samples": [0, 5, 40],
            }
        ]
    )
    assert check_ola_smooth_interpolation(plan)["verdict"] == "pass"


def test_a3_ola_missing_rate_fail():
    plan = _ola_plan(streams=[{"name": "score", "settle_seconds": 1.5, "max_jump": 10}])
    assert check_ola_smooth_interpolation(plan)["verdict"] == "fail"


def test_a3_ola_missing_convergence_fail():
    plan = _ola_plan(streams=[{"name": "score", "rate": 0.2, "max_jump": 10}])
    assert check_ola_smooth_interpolation(plan)["verdict"] == "fail"


def test_a3_ola_empty_streams_fail():
    assert check_ola_smooth_interpolation({"streams": []})["verdict"] == "fail"


def _twojs_scene(**overrides):
    scene = {
        "backend": "svg",
        "layers": [
            {
                "name": "bg",
                "order": 0,
                "elements": [{"type": "rect", "serializable": True}],
            },
            {
                "name": "fg",
                "order": 1,
                "elements": [{"type": "circle", "serializable": True}],
            },
        ],
    }
    scene.update(overrides)
    return scene


def test_a4_twojs_pass():
    assert check_twojs_vector_scene(_twojs_scene())["verdict"] == "pass"


def test_a4_twojs_backend_not_declared_fail():
    assert check_twojs_vector_scene(_twojs_scene(backend="flash"))["verdict"] == "fail"


def test_a4_twojs_layer_order_not_sequential_fail():
    scene = _twojs_scene()
    scene["layers"][1]["order"] = 5
    assert check_twojs_vector_scene(scene)["verdict"] == "fail"


def test_a4_twojs_element_type_unknown_fail():
    scene = _twojs_scene()
    scene["layers"][0]["elements"] = [{"type": "voxel", "serializable": True}]
    assert check_twojs_vector_scene(scene)["verdict"] == "fail"


def test_a4_twojs_element_not_serializable_fail():
    scene = _twojs_scene()
    scene["layers"][0]["elements"] = [{"type": "rect", "serializable": False}]
    assert check_twojs_vector_scene(scene)["verdict"] == "fail"


def test_a4_twojs_empty_layers_fail():
    assert check_twojs_vector_scene({"backend": "svg", "layers": []})["verdict"] == "fail"


def _gif_export(**overrides):
    export = {
        "fps": 12,
        "width": 480,
        "height": 270,
        "palette": "adaptive",
        "loop": 0,
        "max_file_bytes": 2_000_000,
        "encoder": "gifenc",
        "estimated_bytes": 1_500_000,
    }
    export.update(overrides)
    return export


def test_a5_gif_pass():
    assert check_gifenc_gif_export(_gif_export())["verdict"] == "pass"


def test_a5_gif_fps_out_of_range_fail():
    assert check_gifenc_gif_export(_gif_export(fps=60))["verdict"] == "fail"


def test_a5_gif_dimension_out_of_range_fail():
    assert check_gifenc_gif_export(_gif_export(width=2000))["verdict"] == "fail"


def test_a5_gif_palette_not_declared_fail():
    assert check_gifenc_gif_export(_gif_export(palette="rgb"))["verdict"] == "fail"


def test_a5_gif_estimated_over_budget_fail():
    verdict = check_gifenc_gif_export(_gif_export(estimated_bytes=3_000_000))
    assert verdict["verdict"] == "fail"
    assert verdict["issues"][0]["code"] == "estimated_over_budget"


def test_a5_gif_encoder_not_declared_fail():
    assert check_gifenc_gif_export(_gif_export(encoder="webp"))["verdict"] == "fail"


def test_a5_gif_ffmpeg_encoder_pass():
    assert check_gifenc_gif_export(_gif_export(encoder="ffmpeg"))["verdict"] == "pass"


def _konva_stage(**overrides):
    stage = {
        "layers": [
            {"name": "bg", "order": 0},
            {"name": "fg", "order": 1},
        ],
        "interactions": [
            {"type": "drag", "reversible": True},
            {"type": "select", "reversible": True},
        ],
        "export_consistent_with_stage": True,
    }
    stage.update(overrides)
    return stage


def test_a6_konva_pass():
    assert check_konva_interactive_stage(_konva_stage())["verdict"] == "pass"


def test_a6_konva_layer_order_not_sequential_fail():
    stage = _konva_stage()
    stage["layers"][1]["order"] = 3
    assert check_konva_interactive_stage(stage)["verdict"] == "fail"


def test_a6_konva_interaction_not_reversible_fail():
    stage = _konva_stage()
    stage["interactions"] = [{"type": "drag", "reversible": False}]
    verdict = check_konva_interactive_stage(stage)
    assert verdict["verdict"] == "fail"
    assert verdict["issues"][0]["code"] == "interaction_not_reversible"


def test_a6_konva_interaction_type_unknown_fail():
    stage = _konva_stage()
    stage["interactions"] = [{"type": "teleport", "reversible": True}]
    assert check_konva_interactive_stage(stage)["verdict"] == "fail"


def test_a6_konva_export_not_consistent_fail():
    assert (
        check_konva_interactive_stage(_konva_stage(export_consistent_with_stage=False))["verdict"]
        == "fail"
    )


def test_a6_konva_empty_layers_fail():
    assert (
        check_konva_interactive_stage({"layers": [], "export_consistent_with_stage": True})[
            "verdict"
        ]
        == "fail"
    )


def test_b1_explainer_task_contract():
    contract = compile_motion_canvas_explainer_task({"task_id": "t1", "plan": _explainer_plan()})
    assert contract["executed_here"] is False
    assert contract["output_file"] is None
    assert contract["task_id"] == "t1"
    assert contract["scene_count"] == 2


def test_b1_explainer_task_bad_plan_raises():
    with pytest.raises(CapabilityError):
        compile_motion_canvas_explainer_task({"task_id": "t1", "plan": _explainer_plan(scenes=[])})


def test_b1_explainer_task_missing_field_raises():
    with pytest.raises(CapabilityError):
        compile_motion_canvas_explainer_task({"task_id": "t1"})


def test_b2_layout_task_contract():
    contract = compile_motion_layout_transition_task({"task_id": "t2", "plan": _layout_plan()})
    assert contract["executed_here"] is False
    assert contract["output_file"] is None
    assert contract["kinds"] == ["gesture", "layout"]


def test_b2_layout_task_tween_raises():
    with pytest.raises(CapabilityError):
        compile_motion_layout_transition_task(
            {
                "task_id": "t2",
                "plan": _layout_plan(
                    transitions=[{"element": "card", "kind": "tween", "duration_s": 0.4}]
                ),
            }
        )


def test_b3_ola_task_contract():
    contract = compile_ola_interpolation_task({"task_id": "t3", "plan": _ola_plan()})
    assert contract["executed_here"] is False
    assert contract["output_file"] is None
    assert contract["stream_names"] == ["score"]


def test_b3_ola_task_undeclared_jump_raises():
    with pytest.raises(CapabilityError):
        compile_ola_interpolation_task(
            {
                "task_id": "t3",
                "plan": _ola_plan(
                    streams=[
                        {
                            "name": "score",
                            "rate": 0.2,
                            "settle_seconds": 1.5,
                            "max_jump": 10,
                            "samples": [0, 40],
                        }
                    ]
                ),
            }
        )


def test_b4_twojs_task_contract():
    contract = compile_twojs_vector_scene_task({"task_id": "t4", "scene": _twojs_scene()})
    assert contract["executed_here"] is False
    assert contract["output_file"] is None
    assert contract["backend"] == "svg"


def test_b4_twojs_task_bad_backend_raises():
    with pytest.raises(CapabilityError):
        compile_twojs_vector_scene_task({"task_id": "t4", "scene": _twojs_scene(backend="flash")})


def test_b5_gif_task_contract():
    contract = compile_gifenc_gif_export_task({"task_id": "t5", "export": _gif_export()})
    assert contract["executed_here"] is False
    assert contract["output_file"] is None
    assert contract["encoder"] == "gifenc"


def test_b5_gif_task_over_budget_raises():
    with pytest.raises(CapabilityError):
        compile_gifenc_gif_export_task(
            {"task_id": "t5", "export": _gif_export(estimated_bytes=9_000_000)}
        )


def test_b6_konva_task_contract():
    contract = compile_konva_interactive_stage_task({"task_id": "t6", "stage": _konva_stage()})
    assert contract["executed_here"] is False
    assert contract["output_file"] is None
    assert contract["layer_count"] == 2


def test_b6_konva_task_irreversible_raises():
    stage = _konva_stage()
    stage["interactions"] = [{"type": "drag", "reversible": False}]
    with pytest.raises(CapabilityError):
        compile_konva_interactive_stage_task({"task_id": "t6", "stage": stage})


def test_b_schema_unknown_field_raises():
    with pytest.raises(CapabilityError):
        compile_gifenc_gif_export_task({"task_id": "t5", "export": _gif_export(), "surprise": True})


def test_render_smoke_gate_writes_report(tmp_path):
    from hevi.capabilities.gifenc_gif_export_gate import (
        register_gifenc_gif_export_gate_capabilities_once,
    )

    register_gifenc_gif_export_gate_capabilities_once()
    caps = {c.name: c for c in list_capabilities()}
    cap = caps["qa.gifenc_gif_export_gate"]
    result = cap.render(
        {"export": _gif_export()},
        tmp_path,
        duration=1.0,
        aspect="16:9",
        seed=1,
    )
    assert (tmp_path / "gifenc_gif_export_report.json").exists()
    assert result.qa["verdict"] == "pass"


def test_render_smoke_schema_writes_contract(tmp_path):
    from hevi.capabilities.gifenc_gif_export_task_schema import (
        register_gifenc_gif_export_task_schema_capabilities_once,
    )

    register_gifenc_gif_export_task_schema_capabilities_once()
    caps = {c.name: c for c in list_capabilities()}
    cap = caps["video.gifenc_gif_export_task_schema"]
    result = cap.render(
        {"task": {"task_id": "t5", "export": _gif_export()}},
        tmp_path,
        duration=1.0,
        aspect="16:9",
        seed=1,
    )
    assert (tmp_path / "gifenc_gif_export_task_contract.json").exists()
    assert result.qa["executed_here"] is False
