"""Video skills 10 graft tests (A1-A6 gates, B1-B6 fake schemas).

The gate (A) tests assert pass/fail verdicts on good and bad
inputs. The schema (B) tests assert fail-closed behaviour:
``compile_*`` returns a contract declaring ``executed_here``
false and ``output_file`` None on a well-formed input, and
raises ``CapabilityError`` on any shape violation. The
registration test asserts all 12 new capability names are
present exactly once. No test installs or runs any upstream
skill, loads weights, calls a paid API, or touches a GPU.
"""

from __future__ import annotations

import pytest

from hevi.capabilities import list_capabilities
from hevi.capabilities.app_demo_film_gate import check_app_demo_film
from hevi.capabilities.app_demo_film_task_schema import compile_app_demo_film_task
from hevi.capabilities.browser_demo_recording_gate import (
    check_browser_demo_recording,
)
from hevi.capabilities.browser_demo_recording_task_schema import (
    compile_browser_demo_recording_task,
)
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.multilingual_dubbing_pipeline_gate import (
    check_multilingual_dubbing_pipeline,
)
from hevi.capabilities.multilingual_dubbing_task_schema import (
    compile_multilingual_dubbing_task,
)
from hevi.capabilities.multilingual_subtitle_task_schema import (
    compile_multilingual_subtitle_task,
)
from hevi.capabilities.multilingual_subtitle_workflow_gate import (
    check_multilingual_subtitle_workflow,
)
from hevi.capabilities.video_asset_imagegen_gate import check_video_asset_imagegen
from hevi.capabilities.video_asset_imagegen_task_schema import (
    compile_video_asset_imagegen_task,
)
from hevi.capabilities.video_use_orchestration_gate import (
    check_video_use_orchestration,
)
from hevi.capabilities.video_use_orchestration_task_schema import (
    compile_video_use_orchestration_task,
)

NEW_NAMES = [
    "qa.video_use_orchestration_gate",
    "qa.multilingual_subtitle_workflow_gate",
    "qa.browser_demo_recording_gate",
    "qa.video_asset_imagegen_gate",
    "qa.multilingual_dubbing_pipeline_gate",
    "qa.app_demo_film_gate",
    "video.video_use_orchestration_task_schema",
    "video.multilingual_subtitle_task_schema",
    "video.browser_demo_recording_task_schema",
    "video.video_asset_imagegen_task_schema",
    "video.multilingual_dubbing_task_schema",
    "video.app_demo_film_task_schema",
]


def test_registration_names_present_exactly_once():
    names = [c.name for c in list_capabilities()]
    for name in NEW_NAMES:
        assert names.count(name) == 1, name


# --- A1 video-use orchestration increment gate ---


def _orchestration_plan(**overrides):
    plan = {
        "session_memory": {"project_md": "videos/project.md", "last_cut_index": 3},
        "color_grade_chain": [
            {"name": "exposure", "order": 0, "applies_before_subtitles": True},
            {"name": "saturation", "order": 1, "applies_before_subtitles": True},
        ],
        "overlay_layers": [
            {"type": "hyperframes", "cut_range": [0, 2], "ready": True},
            {"type": "remotion", "cut_range": [2, 4], "ready": True},
        ],
        "per_cut_self_check": [
            {"cut_id": "c0", "verdict": "pass", "note": "cut clean"},
            {"cut_id": "c1", "verdict": "pass", "note": "cut clean"},
        ],
        "voice": {"voice_id": "soffy", "authorization_proof": "owner-authorized"},
    }
    plan.update(overrides)
    return plan


def test_a1_orchestration_pass():
    assert check_video_use_orchestration(_orchestration_plan())["verdict"] == "pass"


def test_a1_orchestration_without_session_memory_fail():
    plan = _orchestration_plan()
    del plan["session_memory"]
    assert check_video_use_orchestration(plan)["verdict"] == "fail"


def test_a1_orchestration_grade_order_wrong_fail():
    plan = _orchestration_plan()
    plan["color_grade_chain"][1]["order"] = 0
    assert check_video_use_orchestration(plan)["verdict"] == "fail"


def test_a1_orchestration_grade_after_subtitles_fail():
    plan = _orchestration_plan()
    plan["color_grade_chain"][0]["applies_before_subtitles"] = False
    assert check_video_use_orchestration(plan)["verdict"] == "fail"


def test_a1_orchestration_layer_type_unknown_fail():
    plan = _orchestration_plan()
    plan["overlay_layers"][0]["type"] = "after-effects"
    assert check_video_use_orchestration(plan)["verdict"] == "fail"


def test_a1_orchestration_layer_not_ready_fail():
    plan = _orchestration_plan()
    plan["overlay_layers"][0]["ready"] = False
    assert check_video_use_orchestration(plan)["verdict"] == "fail"


def test_a1_orchestration_cut_verdict_fail_fail():
    plan = _orchestration_plan()
    plan["per_cut_self_check"][1]["verdict"] = "fail"
    assert check_video_use_orchestration(plan)["verdict"] == "fail"


def test_a1_orchestration_duplicate_cut_id_fail():
    plan = _orchestration_plan()
    plan["per_cut_self_check"][1]["cut_id"] = "c0"
    assert check_video_use_orchestration(plan)["verdict"] == "fail"


def test_a1_orchestration_elevenlabs_fail():
    plan = _orchestration_plan()
    plan["voice"] = {"voice_id": "elevenlabs-rachel", "authorization_proof": "key"}
    assert check_video_use_orchestration(plan)["verdict"] == "fail"


def test_a1_orchestration_voice_without_proof_fail():
    plan = _orchestration_plan()
    plan["voice"] = {"voice_id": "soffy"}
    assert check_video_use_orchestration(plan)["verdict"] == "fail"


def test_a1_orchestration_not_object_fail():
    assert check_video_use_orchestration("nope")["verdict"] == "fail"


def test_b1_orchestration_task_contract():
    contract = compile_video_use_orchestration_task(
        {"task_id": "t1", "plan": _orchestration_plan()}
    )
    assert contract["executed_here"] is False
    assert contract["output_file"] is None
    assert contract["layer_count"] == 2
    assert contract["cut_count"] == 2


def test_b1_orchestration_task_bad_plan_raises():
    plan = _orchestration_plan()
    plan["overlay_layers"] = []
    with pytest.raises(CapabilityError):
        compile_video_use_orchestration_task({"task_id": "t1", "plan": plan})


def test_b1_orchestration_task_unknown_field_raises():
    with pytest.raises(CapabilityError):
        compile_video_use_orchestration_task(
            {"task_id": "t1", "plan": _orchestration_plan(), "surprise": True}
        )


def test_b1_orchestration_task_not_object_raises():
    with pytest.raises(CapabilityError):
        compile_video_use_orchestration_task("nope")


# --- A2 multilingual subtitle workflow gate ---


def _subtitle_plan(**overrides):
    plan = {
        "source_language": "zh",
        "target_language": "en",
        "stages": ["transcribe", "translate", "format", "deliver"],
        "formats": ["srt", "vtt"],
        "delivery": "burn",
        "asr_engine": "faster-whisper",
        "cjk_typesetting": True,
    }
    plan.update(overrides)
    return plan


def test_a2_subtitle_zh_to_en_pass():
    assert check_multilingual_subtitle_workflow(_subtitle_plan())["verdict"] == "pass"


def test_a2_subtitle_en_to_zh_pass():
    plan = _subtitle_plan(source_language="en", target_language="zh")
    assert check_multilingual_subtitle_workflow(plan)["verdict"] == "pass"


def test_a2_subtitle_equal_languages_fail():
    plan = _subtitle_plan(target_language="zh")
    assert check_multilingual_subtitle_workflow(plan)["verdict"] == "fail"


def test_a2_subtitle_stages_out_of_order_fail():
    plan = _subtitle_plan(stages=["translate", "transcribe", "format", "deliver"])
    assert check_multilingual_subtitle_workflow(plan)["verdict"] == "fail"


def test_a2_subtitle_format_unknown_fail():
    plan = _subtitle_plan(formats=["srt", "mov"])
    assert check_multilingual_subtitle_workflow(plan)["verdict"] == "fail"


def test_a2_subtitle_delivery_unknown_fail():
    plan = _subtitle_plan(delivery="stream")
    assert check_multilingual_subtitle_workflow(plan)["verdict"] == "fail"


def test_a2_subtitle_cjk_without_typesetting_fail():
    plan = _subtitle_plan()
    del plan["cjk_typesetting"]
    assert check_multilingual_subtitle_workflow(plan)["verdict"] == "fail"


def test_a2_subtitle_oo_cli_fail():
    plan = _subtitle_plan(provider="oo_cli")
    assert check_multilingual_subtitle_workflow(plan)["verdict"] == "fail"


def test_a2_subtitle_asr_engine_missing_fail():
    plan = _subtitle_plan()
    del plan["asr_engine"]
    assert check_multilingual_subtitle_workflow(plan)["verdict"] == "fail"


def test_b2_subtitle_task_contract():
    contract = compile_multilingual_subtitle_task({"task_id": "t2", "plan": _subtitle_plan()})
    assert contract["executed_here"] is False
    assert contract["output_file"] is None
    assert contract["source_language"] == "zh"
    assert contract["formats"] == ["srt", "vtt"]


def test_b2_subtitle_task_bad_plan_raises():
    plan = _subtitle_plan(target_language="zh")
    with pytest.raises(CapabilityError):
        compile_multilingual_subtitle_task({"task_id": "t2", "plan": plan})


def test_b2_subtitle_task_missing_task_id_raises():
    with pytest.raises(CapabilityError):
        compile_multilingual_subtitle_task({"plan": _subtitle_plan()})


# --- A3 browser demo recording gate ---


def _demo_plan(**overrides):
    plan = {
        "capture_source": "hevi-browser",
        "frames": {"fps": 60, "aspect": "4:3", "width": 3840, "height": 2880},
        "interactions": [
            {"type": "mouse_move", "target": "nav", "at_s": 0.5},
            {"type": "click", "target": "signup-button", "at_s": 2.0},
            {"type": "zoom_follow", "target": "settings-panel", "at_s": 4.0},
        ],
        "render": {"tool": "pillow+ffmpeg", "ffprobe_check": True},
        "duration_s": 30,
    }
    plan.update(overrides)
    return plan


def test_a3_demo_pass():
    assert check_browser_demo_recording(_demo_plan())["verdict"] == "pass"


def test_a3_demo_codex_source_fail():
    plan = _demo_plan(capture_source="codex-in-app-browser")
    assert check_browser_demo_recording(plan)["verdict"] == "fail"


def test_a3_demo_fps_out_of_range_fail():
    plan = _demo_plan()
    plan["frames"]["fps"] = 0
    assert check_browser_demo_recording(plan)["verdict"] == "fail"


def test_a3_demo_aspect_unknown_fail():
    plan = _demo_plan()
    plan["frames"]["aspect"] = "21:9"
    assert check_browser_demo_recording(plan)["verdict"] == "fail"


def test_a3_demo_dimension_too_large_fail():
    plan = _demo_plan()
    plan["frames"]["width"] = 5000
    assert check_browser_demo_recording(plan)["verdict"] == "fail"


def test_a3_demo_interaction_type_unknown_fail():
    plan = _demo_plan()
    plan["interactions"][0]["type"] = "teleport"
    assert check_browser_demo_recording(plan)["verdict"] == "fail"


def test_a3_demo_ffprobe_check_missing_fail():
    plan = _demo_plan()
    plan["render"]["ffprobe_check"] = False
    assert check_browser_demo_recording(plan)["verdict"] == "fail"


def test_a3_demo_duration_not_positive_fail():
    plan = _demo_plan(duration_s=0)
    assert check_browser_demo_recording(plan)["verdict"] == "fail"


def test_b3_demo_task_contract():
    contract = compile_browser_demo_recording_task({"task_id": "t3", "plan": _demo_plan()})
    assert contract["executed_here"] is False
    assert contract["output_file"] is None
    assert contract["interaction_count"] == 3


def test_b3_demo_task_bad_plan_raises():
    plan = _demo_plan(capture_source="codex-in-app-browser")
    with pytest.raises(CapabilityError):
        compile_browser_demo_recording_task({"task_id": "t3", "plan": plan})


def test_b3_demo_task_unknown_field_raises():
    with pytest.raises(CapabilityError):
        compile_browser_demo_recording_task(
            {"task_id": "t3", "plan": _demo_plan(), "surprise": True}
        )


# --- A4 video asset imagegen gate ---


def _imagegen_plan(**overrides):
    plan = {
        "assets": [
            {"kind": "cover", "prompt": "red courtyard poster", "route": "cf-flux"},
            {
                "kind": "transparent_png",
                "prompt": "red bow sticker",
                "route": "pollinations",
                "alpha": True,
            },
        ],
        "free_route_only": True,
    }
    plan.update(overrides)
    return plan


def test_a4_imagegen_pass():
    assert check_video_asset_imagegen(_imagegen_plan())["verdict"] == "pass"


def test_a4_imagegen_transparent_png_without_alpha_fail():
    plan = _imagegen_plan()
    del plan["assets"][1]["alpha"]
    assert check_video_asset_imagegen(plan)["verdict"] == "fail"


def test_a4_imagegen_openai_route_fail():
    plan = _imagegen_plan()
    plan["assets"][0]["route"] = "gpt-image-2"
    assert check_video_asset_imagegen(plan)["verdict"] == "fail"


def test_a4_imagegen_free_route_only_false_fail():
    plan = _imagegen_plan(free_route_only=False)
    assert check_video_asset_imagegen(plan)["verdict"] == "fail"


def test_a4_imagegen_kind_unknown_fail():
    plan = _imagegen_plan()
    plan["assets"][0]["kind"] = "3d-model"
    assert check_video_asset_imagegen(plan)["verdict"] == "fail"


def test_a4_imagegen_assets_empty_fail():
    plan = _imagegen_plan(assets=[])
    assert check_video_asset_imagegen(plan)["verdict"] == "fail"


def test_b4_imagegen_task_contract():
    contract = compile_video_asset_imagegen_task({"task_id": "t4", "plan": _imagegen_plan()})
    assert contract["executed_here"] is False
    assert contract["output_file"] is None
    assert contract["asset_count"] == 2
    assert contract["kinds"] == ["cover", "transparent_png"]


def test_b4_imagegen_task_bad_plan_raises():
    plan = _imagegen_plan(free_route_only=False)
    with pytest.raises(CapabilityError):
        compile_video_asset_imagegen_task({"task_id": "t4", "plan": plan})


def test_b4_imagegen_task_not_object_raises():
    with pytest.raises(CapabilityError):
        compile_video_asset_imagegen_task("nope")


# --- A5 multilingual dubbing pipeline gate ---


def _dubbing_plan(**overrides):
    plan = {
        "source_language": "zh",
        "target_language": "en",
        "stages": ["transcribe", "translate", "tts", "align", "mix"],
        "voice": {
            "voice_id": "soffy",
            "authorization_proof": "owner-authorized",
            "provider": "luxtts",
        },
        "alignment": True,
    }
    plan.update(overrides)
    return plan


def test_a5_dubbing_zh_to_en_pass():
    assert check_multilingual_dubbing_pipeline(_dubbing_plan())["verdict"] == "pass"


def test_a5_dubbing_voice_without_proof_fail():
    plan = _dubbing_plan()
    del plan["voice"]["authorization_proof"]
    assert check_multilingual_dubbing_pipeline(plan)["verdict"] == "fail"


def test_a5_dubbing_elevenlabs_provider_fail():
    plan = _dubbing_plan()
    plan["voice"]["provider"] = "elevenlabs"
    assert check_multilingual_dubbing_pipeline(plan)["verdict"] == "fail"


def test_a5_dubbing_clone_fail():
    plan = _dubbing_plan()
    plan["voice"]["clone"] = True
    assert check_multilingual_dubbing_pipeline(plan)["verdict"] == "fail"


def test_a5_dubbing_zero_shot_fail():
    plan = _dubbing_plan()
    plan["voice"]["zero_shot"] = True
    assert check_multilingual_dubbing_pipeline(plan)["verdict"] == "fail"


def test_a5_dubbing_stages_out_of_order_fail():
    plan = _dubbing_plan(stages=["transcribe", "tts", "translate", "align", "mix"])
    assert check_multilingual_dubbing_pipeline(plan)["verdict"] == "fail"


def test_a5_dubbing_alignment_missing_fail():
    plan = _dubbing_plan(alignment=False)
    assert check_multilingual_dubbing_pipeline(plan)["verdict"] == "fail"


def test_b5_dubbing_task_contract():
    contract = compile_multilingual_dubbing_task({"task_id": "t5", "plan": _dubbing_plan()})
    assert contract["executed_here"] is False
    assert contract["output_file"] is None
    assert contract["voice_id"] == "soffy"


def test_b5_dubbing_task_bad_plan_raises():
    plan = _dubbing_plan()
    plan["voice"]["clone"] = True
    with pytest.raises(CapabilityError):
        compile_multilingual_dubbing_task({"task_id": "t5", "plan": plan})


def test_b5_dubbing_task_unknown_field_raises():
    with pytest.raises(CapabilityError):
        compile_multilingual_dubbing_task(
            {"task_id": "t5", "plan": _dubbing_plan(), "surprise": True}
        )


# --- A6 App demo film gate ---


def _app_demo_plan(**overrides):
    plan = {
        "steps": {
            "record_operation": True,
            "analyze_frames": True,
            "narration": True,
            "voiceover": True,
            "device_frame": True,
            "bgm": True,
            "assemble": True,
        },
        "step_order": [
            "record_operation",
            "analyze_frames",
            "narration",
            "voiceover",
            "device_frame",
            "bgm",
            "assemble",
        ],
        "device_frame": {"device": "iphone-16", "frame": True},
        "division_of_labour": "talkback owns the voice, hyperframes owns the motion",
        "each_step_verifiable": True,
        "voice": {"voice_id": "soffy", "authorization_proof": "owner-authorized"},
    }
    plan.update(overrides)
    return plan


def test_a6_app_demo_pass():
    assert check_app_demo_film(_app_demo_plan())["verdict"] == "pass"


def test_a6_app_demo_step_missing_fail():
    plan = _app_demo_plan()
    plan["steps"]["bgm"] = False
    assert check_app_demo_film(plan)["verdict"] == "fail"


def test_a6_app_demo_step_order_wrong_fail():
    plan = _app_demo_plan()
    plan["step_order"] = list(reversed(plan["step_order"]))
    assert check_app_demo_film(plan)["verdict"] == "fail"


def test_a6_app_demo_device_frame_missing_fail():
    plan = _app_demo_plan()
    plan["device_frame"]["frame"] = False
    assert check_app_demo_film(plan)["verdict"] == "fail"


def test_a6_app_demo_division_without_reuse_line_fail():
    plan = _app_demo_plan(division_of_labour="the other tool owns everything")
    assert check_app_demo_film(plan)["verdict"] == "fail"


def test_a6_app_demo_voice_without_proof_fail():
    plan = _app_demo_plan()
    plan["voice"] = {"voice_id": "soffy"}
    assert check_app_demo_film(plan)["verdict"] == "fail"


def test_a6_app_demo_step_not_verifiable_fail():
    plan = _app_demo_plan(each_step_verifiable=False)
    assert check_app_demo_film(plan)["verdict"] == "fail"


def test_b6_app_demo_task_contract():
    contract = compile_app_demo_film_task({"task_id": "t6", "plan": _app_demo_plan()})
    assert contract["executed_here"] is False
    assert contract["output_file"] is None
    assert contract["device"] == "iphone-16"
    assert contract["step_count"] == 7


def test_b6_app_demo_task_bad_plan_raises():
    plan = _app_demo_plan()
    plan["steps"]["bgm"] = False
    with pytest.raises(CapabilityError):
        compile_app_demo_film_task({"task_id": "t6", "plan": plan})


def test_b6_app_demo_task_missing_task_id_raises():
    with pytest.raises(CapabilityError):
        compile_app_demo_film_task({"plan": _app_demo_plan()})


# --- render smoke ---


def test_render_smoke_gate_writes_report(tmp_path):
    from hevi.capabilities.multilingual_subtitle_workflow_gate import (
        register_multilingual_subtitle_workflow_gate_capabilities_once,
    )

    register_multilingual_subtitle_workflow_gate_capabilities_once()
    caps = {c.name: c for c in list_capabilities()}
    cap = caps["qa.multilingual_subtitle_workflow_gate"]
    result = cap.render(
        {"plan": _subtitle_plan()},
        tmp_path,
        duration=1.0,
        aspect="16:9",
        seed=1,
    )
    assert (tmp_path / "multilingual_subtitle_workflow_report.json").exists()
    assert result.qa["verdict"] == "pass"


def test_render_smoke_schema_writes_contract(tmp_path):
    from hevi.capabilities.multilingual_dubbing_task_schema import (
        register_multilingual_dubbing_task_schema_capabilities_once,
    )

    register_multilingual_dubbing_task_schema_capabilities_once()
    caps = {c.name: c for c in list_capabilities()}
    cap = caps["video.multilingual_dubbing_task_schema"]
    result = cap.render(
        {"task": {"task_id": "t5", "plan": _dubbing_plan()}},
        tmp_path,
        duration=1.0,
        aspect="16:9",
        seed=1,
    )
    assert (tmp_path / "multilingual_dubbing_task_contract.json").exists()
    assert result.qa["executed_here"] is False
