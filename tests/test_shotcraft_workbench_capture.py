"""Tests for the shotcraft workbench/capture delta graft: A1-A5 gates
and B1-B2 schemas. Discipline and contract layers only; nothing is
built, captured, or rendered.
"""

import pytest

from hevi.capabilities import beat_sync_honesty_gate as a5
from hevi.capabilities import brand_attribution_gate as a4
from hevi.capabilities import capture_discipline_gate as a3
from hevi.capabilities import capture_kit_schema as b2
from hevi.capabilities import workbench_edit_boundary as a2
from hevi.capabilities import workbench_manifest_gate as a1
from hevi.capabilities import workbench_manifest_schema as b1
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import contains


def _manifest(**overrides):
    plan = {
        "manifest_present": True,
        "manifest_version": "workbench-1",
        "timeline_same_source": True,
        "hand_copied_timeline": False,
        "sections": list(a1.MANIFEST_SECTIONS),
    }
    plan.update(overrides)
    return plan


def _boundary(**overrides):
    plan = {
        "rhythm_constants_exposed": False,
        "demo_cards_time_layer_only": True,
        "edits_stored_in": "localStorage",
        "writes_back_to_source": False,
        "export_formats": ["mp4", "project_json"],
        "frame_identical_claim": False,
        "parity_verified": False,
    }
    plan.update(overrides)
    return plan


def _capture(**overrides):
    plan = {
        "capture_claimed": True,
        "runs_locally": True,
        "seeding_declared": True,
        "real_customer_data": False,
        "copy_source": "project_brief",
        "auth_required": False,
        "paywall_present": False,
    }
    plan.update(overrides)
    return plan


def _brands(**overrides):
    plan = {
        "brands": ["Raycast", "Figma"],
        "no_affiliation_declared": True,
        "no_endorsement_declared": True,
        "per_card_provenance_claimed": False,
        "original_assets_claimed": False,
        "methods_rewritten_declared": True,
    }
    plan.update(overrides)
    return plan


def _beat(**overrides):
    plan = {
        "beat_tracker": "librosa_beat_track",
        "grid_fit": "least_squares_equidistant",
        "residual_tolerance_ms": 15,
        "float_seconds_recorded": True,
        "frame_conversion_last_step": True,
    }
    plan.update(overrides)
    return plan


# A1: workbench manifest gate


def test_a1_manifest_positive():
    report = a1.check_workbench_manifest(_manifest())
    assert report["verdict"] == "pass"
    assert report["ok"] is True
    assert report["sections"] == list(a1.MANIFEST_SECTIONS)
    assert report["manifest_version"] == "workbench-1"


def test_a1_manifest_absent_declared():
    report = a1.check_workbench_manifest(
        {"manifest_present": False, "import_unavailable_declared": True}
    )
    assert report["verdict"] == "pass"


def test_a1_manifest_negatives():
    assert a1.check_workbench_manifest({"manifest_present": False})["verdict"] == "fail"
    assert a1.check_workbench_manifest(_manifest(manifest_version=""))["verdict"] == "fail"
    assert a1.check_workbench_manifest(_manifest(timeline_same_source=False))["verdict"] == "fail"
    assert a1.check_workbench_manifest(_manifest(hand_copied_timeline=True))["verdict"] == "fail"
    assert a1.check_workbench_manifest(_manifest(sections=["shots"]))["verdict"] == "fail"
    assert (
        a1.check_workbench_manifest(_manifest(sections=[*list(a1.MANIFEST_SECTIONS), "extras"]))[
            "verdict"
        ]
        == "fail"
    )
    assert a1.check_workbench_manifest("not-a-plan")["verdict"] == "fail"


# A2: workbench edit boundary gate


def test_a2_boundary_positive():
    report = a2.check_workbench_edit_boundary(_boundary())
    assert report["verdict"] == "pass"
    assert report["parity_status"] == "unverified"


def test_a2_boundary_negatives():
    assert (
        a2.check_workbench_edit_boundary(_boundary(rhythm_constants_exposed=True))["verdict"]
        == "fail"
    )
    assert (
        a2.check_workbench_edit_boundary(_boundary(demo_cards_time_layer_only=False))["verdict"]
        == "fail"
    )
    assert (
        a2.check_workbench_edit_boundary(_boundary(edits_stored_in="server"))["verdict"] == "fail"
    )
    assert (
        a2.check_workbench_edit_boundary(_boundary(writes_back_to_source=True))["verdict"] == "fail"
    )
    assert (
        a2.check_workbench_edit_boundary(_boundary(frame_identical_claim=True))["verdict"] == "fail"
    )
    assert (
        a2.check_workbench_edit_boundary(
            _boundary(frame_identical_claim=True, parity_verified=True)
        )["verdict"]
        == "pass"
    )
    assert a2.check_workbench_edit_boundary(_boundary(export_formats=["mov"]))["verdict"] == "fail"


# A3: capture discipline gate


def test_a3_capture_positive():
    report = a3.check_capture_discipline(_capture())
    assert report["verdict"] == "pass"
    assert report["capture_allowed"] is True


def test_a3_capture_negatives():
    assert a3.check_capture_discipline(_capture(runs_locally=False))["verdict"] == "fail"
    assert a3.check_capture_discipline(_capture(seeding_declared=False))["verdict"] == "fail"
    assert a3.check_capture_discipline(_capture(real_customer_data=True))["verdict"] == "fail"
    assert (
        a3.check_capture_discipline(_capture(copy_source="auto_extracted_from_page"))["verdict"]
        == "fail"
    )
    assert (
        a3.check_capture_discipline(_capture(auth_required=True, auth_handling="fail_closed"))[
            "verdict"
        ]
        == "fail"
    )
    assert (
        a3.check_capture_discipline(_capture(auth_required=True, auth_handling="cookie_reuse"))[
            "verdict"
        ]
        == "fail"
    )
    assert a3.check_capture_discipline(_capture(paywall_present=True))["verdict"] == "fail"
    assert a3.check_capture_discipline(_capture(copy_source="user_supplied"))["verdict"] == "pass"


# A4: brand attribution gate


def test_a4_brands_positive():
    assert len(a4.ACKNOWLEDGED_BRANDS) == 12
    report = a4.check_brand_attribution(_brands())
    assert report["verdict"] == "pass"
    assert report["brands"] == ["Raycast", "Figma"]


def test_a4_brands_negatives():
    assert a4.check_brand_attribution(_brands(brands=["Linear"]))["verdict"] == "fail"
    assert (
        a4.check_brand_attribution(_brands(brands=["Raycast", "UnknownMaker"]))["verdict"] == "fail"
    )
    assert a4.check_brand_attribution(_brands(no_affiliation_declared=False))["verdict"] == "fail"
    assert a4.check_brand_attribution(_brands(no_endorsement_declared=False))["verdict"] == "fail"
    assert (
        a4.check_brand_attribution(_brands(per_card_provenance_claimed=True))["verdict"] == "fail"
    )
    assert a4.check_brand_attribution(_brands(original_assets_claimed=True))["verdict"] == "fail"


# A5: beat sync honesty gate


def test_a5_beat_positive():
    report = a5.check_beat_sync(_beat())
    assert report["verdict"] == "pass"
    assert report["residual_tolerance_ms"] == 15


def test_a5_beat_negatives():
    assert a5.check_beat_sync(_beat(beat_tracker="other"))["verdict"] == "fail"
    assert a5.check_beat_sync(_beat(grid_fit="nearest"))["verdict"] == "fail"
    assert a5.check_beat_sync(_beat(residual_tolerance_ms=30))["verdict"] == "fail"
    assert a5.check_beat_sync(_beat(float_seconds_recorded=False))["verdict"] == "fail"
    assert a5.check_beat_sync(_beat(frame_conversion_last_step=False))["verdict"] == "fail"
    assert (
        a5.check_beat_sync(
            _beat(
                cut_point_error_frames=2.2,
                cut_error_verified=True,
                cut_error_evidence="project_self_report_unverified",
            )
        )["verdict"]
        == "fail"
    )
    assert (
        a5.check_beat_sync(
            _beat(
                cut_point_error_frames=2.2,
                cut_error_verified=False,
                cut_error_evidence="project_self_report_unverified",
            )
        )["verdict"]
        == "pass"
    )


# B1: workbench manifest schema


def test_b1_manifest_schema_shape_only():
    contract = b1.compile_workbench_manifest_contract()
    assert contract["executed_here"] is False
    assert contract["rendered_here"] is False
    assert contract["output_file"] is None
    assert contract["parity_verified"] is False
    assert contract["manifest"]["sections"] == list(a1.MANIFEST_SECTIONS)
    assert contract["manifest"]["speed_bounds"] == [0.25, 4.0]
    assert contract["manifest"]["parity_match_threshold"] == 0.001


def test_b1_manifest_schema_positive():
    contract = b1.compile_workbench_manifest_contract({"manifest": _manifest()})
    assert contract["manifest"]["manifest_version"] == "workbench-1"
    assert contract["editor_built_here"] is False


def test_b1_manifest_schema_negatives():
    with pytest.raises(CapabilityError):
        b1.compile_workbench_manifest_contract(
            {"manifest": _manifest(sections=["shots", "mystery"])}
        )
    with pytest.raises(CapabilityError):
        b1.compile_workbench_manifest_contract({"manifest": _manifest(manifest_version="")})
    with pytest.raises(CapabilityError):
        b1.compile_workbench_manifest_contract(
            {"manifest": dict(_manifest(), rhythm_constants_exposed=True)}
        )
    with pytest.raises(CapabilityError):
        b1.compile_workbench_manifest_contract(
            {
                "manifest": dict(
                    _manifest(),
                    tiers={"time_layer": {"speed": 8.0}},
                )
            }
        )
    with pytest.raises(CapabilityError):
        b1.compile_workbench_manifest_contract(
            {
                "manifest": dict(
                    _manifest(),
                    tiers={"content_style": {"headline": {"type": "gradient", "default": "x"}}},
                )
            }
        )


# B2: capture kit schema


def test_b2_capture_kit_shape_only():
    contract = b2.compile_capture_kit_contract()
    assert contract["executed_here"] is False
    assert contract["output_file"] is None
    assert contract["captured_here"] is False
    assert contract["kit"]["artifacts"] == list(b2.CAPTURE_ARTIFACTS)
    assert contract["kit"]["viewport"]["device_scale_factor"] == 2
    assert contract["kit"]["cutout_background"] == "transparent"
    assert contract["kit"]["copy_extracted_from_page"] is False


def test_b2_capture_kit_positive():
    contract = b2.compile_capture_kit_contract(_capture())
    assert contract["kit"]["artifacts"] == list(b2.CAPTURE_ARTIFACTS)
    assert contract["kit"]["layout_table_fields"] == [
        "element",
        "x",
        "y",
        "width",
        "height",
    ]


def test_b2_capture_kit_negatives():
    with pytest.raises(CapabilityError):
        b2.compile_capture_kit_contract(_capture(runs_locally=False))
    with pytest.raises(CapabilityError):
        b2.compile_capture_kit_contract(_capture(seeding_declared=False))
    with pytest.raises(CapabilityError):
        b2.compile_capture_kit_contract(_capture(real_customer_data=True))
    with pytest.raises(CapabilityError):
        b2.compile_capture_kit_contract(_capture(auth_required=True))
    with pytest.raises(CapabilityError):
        b2.compile_capture_kit_contract(_capture(paywall_present=True))
    with pytest.raises(CapabilityError):
        b2.compile_capture_kit_contract(_capture(artifacts=["full_page_screenshot", "raw_dom"]))


def test_new_capabilities_registered():
    for name in (
        "qa.workbench_manifest_gate",
        "qa.workbench_edit_boundary_gate",
        "qa.capture_discipline_gate",
        "qa.brand_attribution_gate",
        "qa.beat_sync_honesty_gate",
        "video.workbench_manifest_schema",
        "video.capture_kit_schema",
    ):
        assert contains(name), name
