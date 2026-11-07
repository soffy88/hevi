"""Tests for the open-3d-skills graft (clean-room, method only).

A1-A5: pure validators, positive and negative cases. B1/B5:
browser renders are skipped when Playwright/Chromium or the
vendored three.js is unavailable (same guard as the Athenaion
graft tests); pure plan checks always run. No author-reported
number appears as a threshold anywhere in these tests: every
threshold, budget, exposure and bloom value is supplied by the
test itself.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from hevi.capabilities import get as _get_capability
from hevi.capabilities.athenaion_browser import _browser_available
from hevi.capabilities.browser_check_matrix import (
    check_browser_check_plan,
    check_browser_check_report,
)
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.seam_loop_vocabulary import check_seam_loop_scores
from hevi.capabilities.spend_preflight_checklist import check_spend_preflight
from hevi.capabilities.transparent_delivery_contract import (
    check_transparent_delivery_plan,
)
from hevi.capabilities.virtual_clock_contract import check_virtual_clock_plan

BROWSER_OK = _browser_available()


def _good_clock_plan() -> dict:
    return {
        "recording": {
            "time_source_replacement": {
                "performance_now_replaced": True,
                "date_now_replaced": True,
                "raf_uses_virtual_time": True,
            },
            "css_pinned": True,
            "video_handling": "seek_per_frame",
            "record_frame_hook": True,
            "later_queue": True,
            "ready_flag": "window.__hfReady === true",
            "hide_ui_during_recording": True,
            "preserve_drawing_buffer": True,
            "settle": {
                "confirmation": "__hf",
                "two_runs_hash_identical": True,
            },
        }
    }


def _good_matrix_plan() -> dict:
    return {
        "matrix": {
            "browsers": ["chromium", "webkit"],
            "widths": [1440, 768, 390],
            "deep_links": ["https://example.test/a", "https://example.test/b"],
            "ready": "window.__ready === true",
            "wait_ms": 500,
        },
        "unexamined": ["long sessions", "throttled first load"],
        "failure": {
            "exit_code_on_failure": 1,
            "conditions": [
                "page_error", "http_4xx", "http_5xx",
                "blank_canvas", "horizontal_overflow",
            ],
        },
    }


def _good_preflight_plan() -> dict:
    return {
        "preflight": {
            "plan": "Generate three stills, review side by side, then two clips.",
            "asset_list": [
                {"name": "hero", "prompt": "hero still", "model": "model-a", "cost_estimate": 0.5},
                {"name": "clip1", "prompt": "clip prompt", "model": "model-b", "cost_estimate": 1.25},
            ],
            "model_capability": {"model-a": ["still"], "model-b": ["start-end frames"]},
            "cost_calibration": {"total_estimate": 1.75, "basis": "provider price page checked today"},
            "confirmed": True,
            "confirmed_by": "payer",
            "spend_brake": {
                "storyboard": [
                    {"shot_id": "s1", "visual": "hero", "duration_sec": 2},
                ],
                "confirmed": True,
                "smoke_passed": True,
                "batch_size": 2,
            },
        }
    }


def _good_delivery_plan() -> dict:
    return {
        "delivery": {
            "formats": ["stacked_alpha", "vp9_alpha", "webp_frames"],
            "stacked_alpha": {"frame_height_doubled": True},
            "vp9_safari_supported": False,
            "safari_note": "VP9 alpha is not supported in Safari; Safari gets stacked-alpha.",
            "background_checks": [
                "near-black background",
                "light page background",
                "loud brand colour background",
            ],
            "chroma_key_gate_separate": True,
            "self_approval": False,
        }
    }


def _b5_inputs() -> dict:
    preset = lambda elev, azim, inten, hemi, fog, exp: {
        "sun_elevation_deg": elev, "sun_azimuth_deg": azim,
        "sun_intensity": inten, "hemisphere_intensity": hemi,
        "fog_density": fog, "exposure": exp,
        "sky_horizon": "#d8c9a8", "sky_zenith": "#6fa3d8",
        "sun_color": "#ffe8c0", "hemisphere_sky": "#6fa3d8",
        "hemisphere_ground": "#8a7a5a", "fog_color": "#c8d4e0",
    }
    return {
        "presets": {
            "morning": preset(35, 135, 2.4, 0.6, 0.003, 0.9),
            "golden": preset(8, 250, 2.0, 0.45, 0.004, 0.85),
            "night": preset(2, 200, 0.25, 0.18, 0.006, 0.7),
        },
        "quality_params": {
            "low": {"terrain_segments": 24, "shadow_map_size": 256, "pixel_ratio_cap": 1.0},
            "balanced": {"terrain_segments": 48, "shadow_map_size": 512, "pixel_ratio_cap": 1.0},
            "high": {"terrain_segments": 96, "shadow_map_size": 1024, "pixel_ratio_cap": 2.0},
        },
        "post": {
            "bloom": {"strength": 0.35, "radius": 0.6, "threshold": 0.85},
            "gtao": {"enabled": True, "params": {"radius": 0.5}},
        },
        "budget": {"max_frame_ms": 100.0, "max_draw_calls": 1000, "max_triangles": 1000000},
        "vantages": {
            "overview": {"position": [55, 26, 62], "target": [0, 4, 0], "fov": 40},
            "low": {"position": [20, 8, 30], "target": [0, 3, 0], "fov": 40},
        },
        "flights": [
            {"name": "overview_to_low", "from_vantage": "overview",
             "to_vantage": "low", "duration_s": 1.0, "arc_height": 8.0},
        ],
    }


# ---------------------------------------------------------------- A1


def test_a1_good_plan_passes() -> None:
    report = check_virtual_clock_plan(_good_clock_plan())
    assert report["verdict"] == "pass", report["issues"]
    assert report["issues"] == []


def test_a1_missing_css_pin_fails() -> None:
    plan = _good_clock_plan()
    plan["recording"]["css_pinned"] = False
    assert any(i["code"] == "css_not_pinned" for i in check_virtual_clock_plan(plan)["issues"])


def test_a1_missing_time_source_fails() -> None:
    plan = _good_clock_plan()
    plan["recording"]["time_source_replacement"]["date_now_replaced"] = False
    assert any(i["code"] == "time_source_not_replaced" for i in check_virtual_clock_plan(plan)["issues"])


def test_a1_beginframe_mislabel_fails() -> None:
    plan = _good_clock_plan()
    plan["recording"]["capture_method"] = "BeginFrame capture"
    assert any(i["code"] == "beginframe_mislabel" for i in check_virtual_clock_plan(plan)["issues"])


def test_a1_malformed_plan_raises() -> None:
    with pytest.raises(CapabilityError):
        check_virtual_clock_plan({"nope": True})


# ---------------------------------------------------------------- A2


def test_a2_good_plan_passes() -> None:
    report = check_browser_check_plan(_good_matrix_plan())
    assert report["verdict"] == "pass", report["issues"]


def test_a2_missing_webkit_fails() -> None:
    plan = _good_matrix_plan()
    plan["matrix"]["browsers"] = ["chromium"]
    assert any(i["code"] == "browser_missing" for i in check_browser_check_plan(plan)["issues"])


def test_a2_missing_width_fails() -> None:
    plan = _good_matrix_plan()
    plan["matrix"]["widths"] = [1440, 768]
    assert any(i["code"] == "width_missing" for i in check_browser_check_plan(plan)["issues"])


def test_a2_missing_unexamined_fails() -> None:
    plan = _good_matrix_plan()
    plan["unexamined"] = []
    assert any(i["code"] == "unexamined_missing" for i in check_browser_check_plan(plan)["issues"])


def test_a2_report_failing_shot_with_exit_0_fails() -> None:
    report = {
        "shots": [
            {"browser": "chromium", "width": 1440, "failures": ["blank_canvas"]},
        ],
        "exit_code": 0,
    }
    assert any(i["code"] == "exit_code_dishonest" for i in check_browser_check_report(report)["issues"])


def test_a2_report_clean_passes() -> None:
    report = {
        "shots": [
            {"browser": "chromium", "width": 1440, "failures": []},
            {"browser": "webkit", "width": 390, "failures": []},
        ],
        "exit_code": 0,
    }
    assert check_browser_check_report(report)["verdict"] == "pass"


# ---------------------------------------------------------------- A3


def test_a3_all_invisible_passes() -> None:
    data = {
        "thresholds": {"seam_invisible_max": 3.0, "seam_jump_min": 9.0, "loop_jump_max": 5.0},
        "seam_scores": [1.0, 2.5],
        "loop": {"jump": 4.0},
    }
    report = check_seam_loop_scores(data)
    assert report["verdict"] == "pass", report["issues"]
    assert [s["class"] for s in report["seams"]] == ["invisible", "invisible"]


def test_a3_jump_fails() -> None:
    data = {
        "thresholds": {"seam_invisible_max": 3.0, "seam_jump_min": 9.0, "loop_jump_max": 5.0},
        "seam_scores": [12.0],
        "loop": {"jump": 1.0},
    }
    report = check_seam_loop_scores(data)
    assert report["verdict"] == "fail"
    assert report["seams"][0]["class"] == "jump"


def test_a3_visible_band_fails() -> None:
    data = {
        "thresholds": {"seam_invisible_max": 3.0, "seam_jump_min": 9.0, "loop_jump_max": 5.0},
        "seam_scores": [5.0],
        "loop": {"jump": 1.0},
    }
    report = check_seam_loop_scores(data)
    assert report["verdict"] == "fail"
    assert report["seams"][0]["class"] == "visible"


def test_a3_missing_thresholds_is_not_checked_never_pass() -> None:
    report = check_seam_loop_scores({"seam_scores": [1.0], "loop": {"jump": 1.0}})
    assert report["verdict"] == "not_checked"
    assert report["ok"] is False


def test_a3_missing_scores_is_not_checked() -> None:
    data = {
        "thresholds": {"seam_invisible_max": 3.0, "seam_jump_min": 9.0, "loop_jump_max": 5.0},
        "loop": {"jump": 1.0},
    }
    assert check_seam_loop_scores(data)["verdict"] == "not_checked"


def test_a3_loop_jump_too_large_fails() -> None:
    data = {
        "thresholds": {"seam_invisible_max": 3.0, "seam_jump_min": 9.0, "loop_jump_max": 5.0},
        "seam_scores": [1.0],
        "loop": {"jump": 8.0},
    }
    assert check_seam_loop_scores(data)["verdict"] == "fail"


# ---------------------------------------------------------------- A4


def test_a4_good_plan_passes() -> None:
    report = check_spend_preflight(_good_preflight_plan())
    assert report["verdict"] == "pass", report["issues"]


def test_a4_missing_confirmation_fails() -> None:
    plan = _good_preflight_plan()
    plan["preflight"]["confirmed"] = "yes"
    assert any(i["code"] == "confirmation_missing" for i in check_spend_preflight(plan)["issues"])


def test_a4_missing_cost_calibration_fails() -> None:
    plan = _good_preflight_plan()
    del plan["preflight"]["cost_calibration"]
    assert any(
        i["code"].startswith("cost_calibration") for i in check_spend_preflight(plan)["issues"]
    )


def test_a4_spend_brake_refusal_fails() -> None:
    plan = _good_preflight_plan()
    plan["preflight"]["spend_brake"]["smoke_passed"] = False
    assert any(i["code"] == "spend_brake_refused" for i in check_spend_preflight(plan)["issues"])


def test_a4_asset_without_cost_fails() -> None:
    plan = _good_preflight_plan()
    del plan["preflight"]["asset_list"][0]["cost_estimate"]
    assert any(i["code"] == "asset_cost_missing" for i in check_spend_preflight(plan)["issues"])


# ---------------------------------------------------------------- A5


def test_a5_good_plan_passes() -> None:
    report = check_transparent_delivery_plan(_good_delivery_plan())
    assert report["verdict"] == "pass", report["issues"]


def test_a5_safari_claim_wrong_fails() -> None:
    plan = _good_delivery_plan()
    plan["delivery"]["vp9_safari_supported"] = True
    assert any(i["code"] == "safari_claim_wrong" for i in check_transparent_delivery_plan(plan)["issues"])


def test_a5_missing_format_fails() -> None:
    plan = _good_delivery_plan()
    plan["delivery"]["formats"] = ["stacked_alpha"]
    assert any(i["code"] == "format_missing" for i in check_transparent_delivery_plan(plan)["issues"])


def test_a5_missing_background_fails() -> None:
    plan = _good_delivery_plan()
    plan["delivery"]["background_checks"] = ["near-black background"]
    assert any(
        i["code"] == "background_check_missing"
        for i in check_transparent_delivery_plan(plan)["issues"]
    )


def test_a5_self_approval_fails() -> None:
    plan = _good_delivery_plan()
    plan["delivery"]["self_approval"] = True
    assert any(i["code"] == "self_approval_claim" for i in check_transparent_delivery_plan(plan)["issues"])


# ---------------------------------------------------------------- Registry


def test_registry_resolves_all_new_capabilities() -> None:
    for name in (
        "qa.virtual_clock_contract",
        "qa.browser_check_matrix",
        "qa.seam_loop_vocabulary",
        "qa.spend_preflight_checklist",
        "qa.transparent_delivery_contract",
        "video.virtual_clock_recorder",
        "world.threejs_imaging_upgrade",
    ):
        assert _get_capability(name).name == name


# ---------------------------------------------------------------- B1


@pytest.mark.skipif(not BROWSER_OK, reason="Playwright/Chromium or vendored three.js unavailable")
def test_b1_two_runs_hash_identical_and_mp4_exists(tmp_path: Path) -> None:
    from hevi.capabilities.virtual_clock_recorder import (
        build_test_page,
        record_virtual_clock,
    )

    html = build_test_page(width=320, height=180, fps=20, duration_s=1.0)
    report = record_virtual_clock(
        html=html, out_dir=tmp_path / "b1", width=320, height=180,
        fps=20, duration_s=1.0, runs=2, encode=True,
    )
    assert report["verdict"] == "pass", report["issues"]
    assert report["hashes_identical"] is True
    assert report["frame_count"] == 20
    assert report["capture_method"].startswith("whole-frame screenshot")
    assert "not BeginFrame capture" in report["capture_method"]
    mp4 = Path(report["encoded"]["mp4"])
    assert mp4.is_file() and mp4.stat().st_size > 0
    probe = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json",
         "-show_streams", "-show_format", str(mp4)],
        capture_output=True, text=True, timeout=60,
    )
    info = json.loads(probe.stdout)
    stream = info["streams"][0]
    assert stream["codec_name"] == "h264"
    assert stream["avg_frame_rate"] == "20/1"


def test_b1_plan_gate_rejects_missing_threshold_free_defaults() -> None:
    # B1 has no thresholds of its own: fps must be supplied as a
    # positive integer; a bad fps raises rather than defaulting.
    from hevi.capabilities.virtual_clock_recorder import record_virtual_clock

    with pytest.raises(CapabilityError):
        record_virtual_clock(
            html="<html></html>", out_dir=Path("/tmp/nope-b1"),
            width=320, height=180, fps=0, duration_s=1.0, runs=1, encode=False,
        )


# ---------------------------------------------------------------- B5


def test_b5_plan_gate_requires_caller_values() -> None:
    from hevi.capabilities.threejs_imaging_upgrade import validate_upgrade_plan

    plan = {
        "upgrade": {
            "presets": {"morning": {}},
            "quality": "balanced",
            "quality_params": {},
            "recording_never_downgrades": True,
            "post": {"bloom": {}, "gtao": {"enabled": False}},
            "budget": {},
            "vantages": {"overview": {"position": [0, 0, 0], "target": [0, 0, 0], "fov": 40}},
            "flights": [],
        }
    }
    report = validate_upgrade_plan(plan)
    assert report["verdict"] == "fail"
    codes = {i["code"] for i in report["issues"]}
    assert "preset_value_missing" in codes
    assert "budget_value_missing" in codes
    assert "quality_tier_missing" in codes


@pytest.mark.skipif(not BROWSER_OK, reason="Playwright/Chromium or vendored three.js unavailable")
def test_b5_three_presets_and_two_run_hash_identity(tmp_path: Path) -> None:
    from hevi.capabilities.threejs_imaging_upgrade import render_upgrade

    inputs = _b5_inputs()
    report = render_upgrade(
        out_dir=tmp_path / "b5", width=320, height=180, fps=5,
        duration_s=1.0, quality="balanced", seed=0, runs=2, **inputs,
    )
    assert report["verdict"] == "pass", report["issues"]
    assert report["hashes_identical"] is True
    assert report["gtao_applied"] is False
    assert report["post_stack_applied"] == ["RenderPass", "UnrealBloomPass", "OutputPass"]
    names = [s["name"] for s in report["runs"][0]["shots"]]
    assert names[:3] == ["preset_morning", "preset_golden", "preset_night"]
    for shot in report["runs"][0]["shots"]:
        assert shot["stats"]["calls"] > 0
        assert shot["stats"]["triangles"] > 0
    assert all(c["frame_ms"] == "not_checked" for c in report["budget_checks"])


@pytest.mark.skipif(not BROWSER_OK, reason="Playwright/Chromium or vendored three.js unavailable")
def test_b5_tiny_budget_fails_on_draw_calls(tmp_path: Path) -> None:
    from hevi.capabilities.threejs_imaging_upgrade import render_upgrade

    inputs = _b5_inputs()
    inputs["budget"] = {"max_frame_ms": 100.0, "max_draw_calls": 1, "max_triangles": 1000000}
    report = render_upgrade(
        out_dir=tmp_path / "b5tiny", width=320, height=180, fps=5,
        duration_s=1.0, quality="balanced", seed=0, runs=1, **inputs,
    )
    assert report["verdict"] == "fail"
    assert any(i["code"] == "budget_draw_calls_exceeded" for i in report["issues"])
