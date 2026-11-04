"""Tests for the video-shotcraft graft (A1-A6 gates, B1 index, B2 fake adapter)."""

import pytest

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import contains

from hevi.capabilities import (
    shotcraft_card_fidelity_gate as a1,
    jianying_export_contract_gate as a2,
    shotcraft_theme_vocabulary as a3,
    preview_provenance_gate as a4,
    sfx_sourcing_gate as a5,
    ink_press_structure_gate as a6,
    shotcraft_card_index as b1,
    jianying_draft_adapter as b2,
)


def _good_card(name="crash-zoom-punch"):
    return {
        "name": name,
        "source": "tuned",
        "tuned_params_present": True,
        "demo_ref": "demos/camera/crash-zoom-punch",
    }


def test_a1_pass_and_unknown_name_fails():
    assert a1.check_shotcraft_card_fidelity(
        {"cards": [_good_card()]}
    )["verdict"] == "pass"
    bad = a1.check_shotcraft_card_fidelity(
        {"cards": [_good_card("not-a-real-card")]}
    )
    assert bad["verdict"] == "fail"
    assert any(
        i["code"].endswith("unknown_card_name") for i in bad["issues"]
    )


def test_a1_synthesized_source_and_missing_params_fail():
    synth = _good_card()
    synth["source"] = "synthesized"
    bad = a1.check_shotcraft_card_fidelity({"cards": [synth]})
    assert bad["verdict"] == "fail"
    assert any(
        i["code"].endswith("synthesized_catalogue_not_tuned")
        for i in bad["issues"]
    )
    no_params = _good_card()
    no_params["tuned_params_present"] = False
    bad2 = a1.check_shotcraft_card_fidelity({"cards": [no_params]})
    assert bad2["verdict"] == "fail"
    assert any(
        i["code"].endswith("tuned_params_missing") for i in bad2["issues"]
    )
    no_source = _good_card()
    del no_source["source"]
    bad3 = a1.check_shotcraft_card_fidelity({"cards": [no_source]})
    assert bad3["verdict"] == "fail"
    assert any(
        i["code"].endswith("source_undeclared") for i in bad3["issues"]
    )
    no_demo = _good_card()
    no_demo["demo_ref"] = "elsewhere/card"
    bad4 = a1.check_shotcraft_card_fidelity({"cards": [no_demo]})
    assert bad4["verdict"] == "fail"
    assert any(
        i["code"].endswith("demo_ref_missing") for i in bad4["issues"]
    )


def test_a1_vocabulary_is_124():
    assert len(a1.tuned_card_names()) == 124
    assert "spotlight-hero-card" in a1.tuned_card_names()
    assert "deck-deal-flyin" in a1.tuned_card_names()


def _good_export_plan():
    return {
        "layering": {
            "baked_plate_clean": True,
            "editable_tracks": ["subtitle_native", "audio_native"],
        },
        "boundary_rule": "round_each_endpoint_then_subtract",
        "one_way_notice_acknowledged": True,
        "device_fingerprint_not_shared": True,
        "executed_here": False,
    }


def test_a2_pass_and_each_declaration_required():
    assert a2.check_jianying_export_contract(
        _good_export_plan()
    )["verdict"] == "pass"
    for key, bad_value in [
        ("boundary_rule", "round_total_then_split"),
        ("one_way_notice_acknowledged", False),
        ("device_fingerprint_not_shared", False),
        ("executed_here", True),
    ]:
        plan = _good_export_plan()
        plan[key] = bad_value
        assert a2.check_jianying_export_contract(plan)["verdict"] == "fail"
    plan = _good_export_plan()
    plan["layering"]["baked_plate_clean"] = False
    assert a2.check_jianying_export_contract(plan)["verdict"] == "fail"
    plan = _good_export_plan()
    plan["layering"]["editable_tracks"] = []
    assert a2.check_jianying_export_contract(plan)["verdict"] == "fail"


def test_a3_presets_precedence_and_ink_press():
    assert a3.check_shotcraft_theme({"theme": "Midnight"})["verdict"] == "pass"
    assert a3.check_shotcraft_theme(
        {
            "theme": "Sage",
            "palette_precedence": [
                "schema_default",
                "preset_default",
                "project_palette",
                "explicit_clip_edit",
            ],
        }
    )["verdict"] == "pass"
    assert a3.check_shotcraft_theme({"theme": "No Such Theme"})[
        "verdict"
    ] == "fail"
    assert len(a3.THEME_PRESETS) == 9
    bad_order = a3.check_shotcraft_theme(
        {
            "theme": "Coral",
            "palette_precedence": ["project_palette", "preset_default"],
        }
    )
    assert bad_order["verdict"] == "fail"
    recolor = a3.check_shotcraft_theme(
        {"theme": "Ink Press", "palette_override": {"accent": "#ff0000"}}
    )
    assert recolor["verdict"] == "fail"
    assert any(
        i["code"] == "ink_press_not_recolorable" for i in recolor["issues"]
    )
    legacy_undeclared = a3.check_shotcraft_theme({"theme": "coral-burst"})
    assert legacy_undeclared["verdict"] == "fail"
    legacy_declared = a3.check_shotcraft_theme(
        {"theme": "coral-burst", "legacy_alias": True}
    )
    assert legacy_declared["verdict"] == "pass"


def test_a4_poster_and_frame_identical_rules():
    assert a4.check_preview_provenance(
        {
            "preview_kind": "release_mp4",
            "source_ref": "release/gallery-media",
            "frame_identical_claim": False,
        }
    )["verdict"] == "pass"
    poster = a4.check_preview_provenance(
        {"preview_kind": "local_poster", "used_as_motion_evidence": True}
    )
    assert poster["verdict"] == "fail"
    assert any(
        i["code"] == "poster_not_motion_evidence" for i in poster["issues"]
    )
    assert a4.check_preview_provenance(
        {"preview_kind": "local_poster", "used_as_motion_evidence": False}
    )["verdict"] == "pass"
    claim = a4.check_preview_provenance(
        {"preview_kind": "rendered_local", "frame_identical_claim": True}
    )
    assert claim["verdict"] == "fail"
    assert any(
        i["code"] == "frame_identical_unverified" for i in claim["issues"]
    )
    assert a4.check_preview_provenance(
        {
            "preview_kind": "rendered_local",
            "frame_identical_claim": True,
            "frame_identical_verified": True,
        }
    )["verdict"] == "pass"
    no_ref = a4.check_preview_provenance({"preview_kind": "release_mp4"})
    assert no_ref["verdict"] == "fail"
    assert any(
        i["code"] == "release_source_ref_missing" for i in no_ref["issues"]
    )


def test_a5_cc0_ccby_key_and_unknown_fail_closed():
    good = {
        "tracks": [
            {"source": "freesound", "license": "CC0", "key_required": False},
            {
                "source": "freesound",
                "license": "CC BY",
                "attribution_entry": "Artist, Track, CC BY",
                "key_required": False,
            },
        ],
        "attribution_list": ["Artist, Track, CC BY"],
    }
    assert a5.check_sfx_sourcing(good)["verdict"] == "pass"
    no_attr = {
        "tracks": [
            {
                "source": "freesound",
                "license": "CC BY",
                "key_required": False,
            }
        ]
    }
    bad = a5.check_sfx_sourcing(no_attr)
    assert bad["verdict"] == "fail"
    assert any(
        i["code"].endswith("attribution_entry_missing") for i in bad["issues"]
    )
    keyed = {
        "tracks": [
            {"source": "vendor", "license": "CC0", "key_required": True}
        ]
    }
    assert a5.check_sfx_sourcing(keyed)["verdict"] == "fail"
    unknown = {
        "tracks": [
            {"source": "", "license": "CC0", "key_required": False}
        ]
    }
    bad2 = a5.check_sfx_sourcing(unknown)
    assert bad2["verdict"] == "fail"
    assert any(
        i["code"].endswith("source_unknown") for i in bad2["issues"]
    )
    bad_license = {
        "tracks": [
            {"source": "web", "license": "???", "key_required": False}
        ]
    }
    assert a5.check_sfx_sourcing(bad_license)["verdict"] == "fail"


def _good_ink_press_plan():
    shots = []
    start = 0
    widths = [100, 110, 120, 110, 100, 110, 120, 110, 105, 100]
    for i, width in enumerate(widths):
        shots.append(
            {"shot_id": f"s{i+1}", "start_frame": start, "end_frame": start + width}
        )
        start += width
    assert start == 1085
    return {
        "width": 1920,
        "height": 1080,
        "fps": 30,
        "frames": 1085,
        "shots": shots,
        "sfx_cue_sheet": [{"frame": 0, "cue": "riser"}],
        "rendered_here": False,
    }


def test_a6_structure_pass_and_grid_failures():
    assert a6.check_ink_press_structure(
        _good_ink_press_plan()
    )["verdict"] == "pass"
    for key, bad_value in [
        ("width", 1280),
        ("fps", 24),
        ("frames", 1080),
        ("rendered_here", True),
    ]:
        plan = _good_ink_press_plan()
        plan[key] = bad_value
        assert a6.check_ink_press_structure(plan)["verdict"] == "fail"
    plan = _good_ink_press_plan()
    plan["shots"] = plan["shots"][:9]
    assert a6.check_ink_press_structure(plan)["verdict"] == "fail"
    plan = _good_ink_press_plan()
    plan["shots"][3]["start_frame"] += 5
    assert a6.check_ink_press_structure(plan)["verdict"] == "fail"
    plan = _good_ink_press_plan()
    plan["sfx_cue_sheet"] = []
    assert a6.check_ink_press_structure(plan)["verdict"] == "fail"


def test_b1_index_124_and_lookup():
    assert b1.check_card_index()["verdict"] == "pass"
    assert len(b1.list_shotcraft_cards()) == 124
    assert len(b1.list_shotcraft_cards("camera")) == 10
    assert len(b1.list_shotcraft_cards("typography")) == 22
    card = b1.get_shotcraft_card("mosaic-reframe")
    assert card is not None
    assert card["category"] == "transition"
    assert card["tuned"] is True
    assert card["verified_by_hevi_render"] is False
    assert b1.get_shotcraft_card("no-such-card") is None
    assert b1.get_shotcraft_card("spotlight-hero-card")["demo_ref"].startswith(
        "demos/"
    )


def test_b2_contract_fake_and_platform_boundary():
    plan = {
        "shots": [
            {"shot_id": "s1", "start_frame": 0, "end_frame": 500},
            {"shot_id": "s2", "start_frame": 500, "end_frame": 1085},
        ]
    }
    contract = b2.compile_jianying_draft_contract(plan)
    assert contract["executed_here"] is False
    assert contract["draft_file"] is None
    assert contract["total_frames"] == 1085
    assert len(contract["clips"]) == 2
    assert contract["clips"][0]["baked_plate_clean"] is True
    assert len(contract["subtitle_track"]) == 2
    assert len(contract["audio_track"]) == 2
    assert (
        contract["platform"]["windows"]["status"]
        == "not_verified_on_real_hardware"
    )
    assert (
        contract["platform"]["mac"]["status"]
        == "upstream_self_reported_verified"
    )
    with pytest.raises(CapabilityError):
        b2.compile_jianying_draft_contract(
            {
                "shots": [
                    {"shot_id": "s1", "start_frame": 0, "end_frame": 500},
                    {"shot_id": "s2", "start_frame": 501, "end_frame": 1085},
                ]
            }
        )
    with pytest.raises(CapabilityError):
        b2.compile_jianying_draft_contract({"shots": []})


def test_all_eight_capabilities_registered():
    for name in [
        "qa.shotcraft_card_fidelity_gate",
        "qa.jianying_export_contract_gate",
        "qa.shotcraft_theme_vocabulary",
        "qa.preview_provenance_gate",
        "qa.sfx_sourcing_gate",
        "qa.ink_press_structure_gate",
        "video.shotcraft_card_index",
        "video.jianying_draft_adapter",
    ]:
        assert contains(name), name
