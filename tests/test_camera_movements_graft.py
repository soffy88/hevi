"""Tests for the aicameramovements graft (A1-A6 gates, B1 index, B2 fake assembler)."""

import pytest

from hevi.capabilities import (
    camera_movement_clause_assembler as b2,
    camera_movement_end_gate as a3,
    camera_movement_four_field_gate as a2,
    camera_movement_index as b1,
    camera_movement_vocabulary_gate as a1,
    slow_zoom_clarification as a6,
    special_movement_flag_gate as a5,
    zoom_track_distinction_gate as a4,
)
from hevi.capabilities.cinematic_techniques import load_movements
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.prompt_compiler import resolve_movement

NEW_IDS = [
    "helicopter_shot",
    "tilt_shift",
    "infinite_zoom",
    "earth_zoom_out",
    "time_lapse",
    "pass_through_objects",
]


def _entries_missing(movement_id):
    rows = [dict(r) for r in load_movements()]
    return [r for r in rows if r["id"] != movement_id]


# ---- A1 vocabulary gate ----


def test_a1_catalogue_is_46_with_all_six_new_movements():
    report = a1.check_movement_vocabulary()
    assert report["verdict"] == "pass"
    assert report["vocabulary_size"] == 46
    assert report["new_movements_found"] == sorted(NEW_IDS)
    assert len(a1.vocabulary_ids()) == 46
    for movement_id in NEW_IDS:
        assert a1.check_movement_vocabulary([movement_id])["verdict"] == "pass"


def test_a1_unknown_claimed_id_and_missing_new_movement_fail():
    bad = a1.check_movement_vocabulary(["not_a_movement"])
    assert bad["verdict"] == "fail"
    assert any(i["code"].startswith("unknown_movement_id") for i in bad["issues"])
    for movement_id in NEW_IDS:
        missing = a1.check_movement_vocabulary(
            entries=_entries_missing(movement_id)
        )
        assert missing["verdict"] == "fail"
        assert any(
            i["code"] == f"new_movement_missing:{movement_id}"
            for i in missing["issues"]
        )


def test_a1_new_movement_wrong_category_fails():
    rows = [dict(r) for r in load_movements()]
    for row in rows:
        if row["id"] == "helicopter_shot":
            row["category"] = "Specials"
    bad = a1.check_movement_vocabulary(entries=rows)
    assert bad["verdict"] == "fail"
    assert any(
        i["code"] == "new_movement_category:helicopter_shot"
        for i in bad["issues"]
    )


# ---- A2 four-field gate ----


def test_a2_all_46_entries_have_four_fields():
    report = a2.check_movement_four_fields()
    assert report["verdict"] == "pass"
    assert report["checked"] == 46
    good = dict(load_movements()[0])
    assert a2.check_four_fields(good)["verdict"] == "pass"


def test_a2_each_missing_or_blank_field_fails():
    base = dict(load_movements()[0])
    for field in a2.FOUR_FIELDS:
        no_field = dict(base)
        del no_field[field]
        bad = a2.check_four_fields(no_field)
        assert bad["verdict"] == "fail"
        assert any(
            i["code"].endswith(f"field_missing:{field}") for i in bad["issues"]
        )
        blank = dict(base)
        blank[field] = "   "
        bad2 = a2.check_four_fields(blank)
        assert bad2["verdict"] == "fail"
        assert any(
            i["code"].endswith(f"field_blank:{field}") for i in bad2["issues"]
        )
    assert a2.check_four_fields("not an entry")["verdict"] == "fail"


# ---- A3 landing gate ----


def test_a3_all_46_entries_have_end_and_clause_marker_required():
    assert a3.check_all_movement_ends()["verdict"] == "pass"
    good = dict(load_movements()[0])
    assert a3.check_movement_end(good)["verdict"] == "pass"
    clause = "Camera movement: turn right. Speed: smooth. End: rest on the new frame."
    assert a3.check_movement_end(clause)["verdict"] == "pass"
    assert a3.check_movement_end({"clause": clause})["verdict"] == "pass"


def test_a3_missing_blank_and_markerless_end_fail():
    no_end = dict(load_movements()[0])
    del no_end["end"]
    assert a3.check_movement_end(no_end)["verdict"] == "fail"
    blank = dict(load_movements()[0])
    blank["end"] = ""
    assert a3.check_movement_end(blank)["verdict"] == "fail"
    assert a3.check_movement_end("Camera movement: turn right. Speed: smooth.")[
        "verdict"
    ] == "fail"
    assert a3.check_movement_end("Camera movement: turn right. End:")[
        "verdict"
    ] == "fail"


# ---- A4 zoom/track distinction ----


def test_a4_mechanism_families_cover_the_vocabulary():
    assert a4.classify_mechanism("slow_zoom_in") == "zoom"
    assert a4.classify_mechanism("dolly_in") == "body"
    assert a4.classify_mechanism("helicopter_shot") == "body"
    assert a4.classify_mechanism("pass_through_objects") == "body"
    assert a4.classify_mechanism("pan_right") == "other"
    assert a4.classify_mechanism("time_lapse") == "other"
    assert a4.classify_mechanism("earth_zoom_out") == "other"


def test_a4_catalogue_movement_texts_pass_their_own_family():
    for row in load_movements():
        claim = {"movement_id": row["id"], "mechanism_text": row["movement"]}
        report = a4.check_zoom_track_distinction(claim)
        assert report["verdict"] == "pass", (row["id"], report)


def test_a4_zoom_described_as_body_movement_fails():
    for movement_id in ("slow_zoom_in", "fast_zoom_out", "crash_zoom_in"):
        bad = a4.check_zoom_track_distinction(
            {
                "movement_id": movement_id,
                "mechanism_text": "Move the camera physically forward toward the subject.",
            }
        )
        assert bad["verdict"] == "fail"
        assert any(
            i["code"] == "zoom_described_as_body_movement" for i in bad["issues"]
        )


def test_a4_body_described_as_zoom_fails():
    for movement_id in ("dolly_in", "truck_right", "helicopter_shot"):
        bad = a4.check_zoom_track_distinction(
            {
                "movement_id": movement_id,
                "mechanism_text": "Lengthen the focal length toward the subject.",
            }
        )
        assert bad["verdict"] == "fail"
        assert any(i["code"] == "body_described_as_zoom" for i in bad["issues"])
    unknown = a4.check_zoom_track_distinction(
        {"movement_id": "no_such_move", "mechanism_text": "Move forward."}
    )
    assert unknown["verdict"] == "fail"


# ---- A5 special flag gate ----


def test_a5_special_movements_require_flags_and_ordinary_pass():
    assert a5.check_special_movement_flags(
        {
            "movement_id": "earth_zoom_out",
            "composite_segments": ["street", "city", "planet"],
        }
    )["verdict"] == "pass"
    assert a5.check_special_movement_flags(
        {"movement_id": "infinite_zoom", "composite_segments": ["room", "world"]}
    )["verdict"] == "pass"
    assert a5.check_special_movement_flags(
        {"movement_id": "time_lapse", "compression_ratio": "60x"}
    )["verdict"] == "pass"
    assert a5.check_special_movement_flags(
        {"movement_id": "dolly_in"}
    )["verdict"] == "pass"


def test_a5_missing_flags_fail_per_movement():
    for movement_id in ("earth_zoom_out", "infinite_zoom"):
        bad = a5.check_special_movement_flags({"movement_id": movement_id})
        assert bad["verdict"] == "fail"
        assert any(
            i["code"] == "special_flag_missing:composite_segments"
            for i in bad["issues"]
        )
    bad = a5.check_special_movement_flags({"movement_id": "time_lapse"})
    assert bad["verdict"] == "fail"
    assert any(
        i["code"] == "special_flag_missing:time_compression"
        for i in bad["issues"]
    )
    empty = a5.check_special_movement_flags(
        {"movement_id": "earth_zoom_out", "composite_segments": []}
    )
    assert empty["verdict"] == "fail"
    assert a5.check_special_movement_flags({"movement_id": "nope"})[
        "verdict"
    ] == "fail"


# ---- A6 slow-zoom clarification ----


def test_a6_slow_zoom_ids_are_legal_and_resolve_in_prompt_compiler():
    report = a6.check_slow_zoom_status()
    assert report["verdict"] == "pass"
    assert report["status"] == {
        "slow_zoom_in": "legal_hevi_id",
        "slow_zoom_out": "legal_hevi_id",
    }
    assert "H3 benchmark" in a6.slow_zoom_clarification_text()
    assert resolve_movement("slow_zoom_in")[0] == "slow_zoom_in"
    assert resolve_movement("slow_zoom_out")[0] == "slow_zoom_out"
    assert resolve_movement("慢推变焦")[0] == "slow_zoom_in"


def test_a6_banning_slow_zoom_or_dropping_the_id_fails():
    bad = a6.check_slow_zoom_status(banned_ids=["slow_zoom_in"])
    assert bad["verdict"] == "fail"
    assert any(
        i["code"] == "slow_zoom_wrongly_banned:slow_zoom_in"
        for i in bad["issues"]
    )
    rows = [dict(r) for r in load_movements() if r["id"] != "slow_zoom_out"]
    missing = a6.check_slow_zoom_status(entries=rows)
    assert missing["verdict"] == "fail"
    assert any(
        i["code"] == "slow_zoom_id_missing:slow_zoom_out"
        for i in missing["issues"]
    )


# ---- B1 unified index ----


def test_b1_index_is_46_single_source_with_category_counts():
    report = b1.check_movement_index()
    assert report["verdict"] == "pass"
    assert report["movement_count"] == 46
    assert report["category_count"] == 7
    assert report["category_counts"] == b1.EXPECTED_CATEGORY_COUNTS
    rows = b1.list_camera_movements()
    assert len(rows) == 46
    assert len({r["id"] for r in rows}) == 46
    assert len(b1.list_camera_movements("Specials")) == 6
    assert len(b1.list_camera_movements("Drone/Crane")) == 5
    for row in rows:
        assert row["verified_by_hevi_render"] is False
        assert row["mechanism"] in ("zoom", "body", "other")
    assert b1.get_camera_movement("earth_zoom_out")["special_flag"] == (
        "composite_segments"
    )
    assert b1.get_camera_movement("time_lapse")["special_flag"] == (
        "time_compression"
    )
    assert b1.get_camera_movement("dolly_in")["special_flag"] is None
    assert b1.get_camera_movement("no_such_move") is None
    assert b1.get_camera_movement("tilt_shift")["name_zh"] == "移轴微缩"


# ---- B2 clause assembler (fake) ----


def test_b2_assembles_four_field_clause_and_keeps_scene_separate():
    contract = b2.assemble_camera_clause(
        "dolly_in",
        scene_clause="A scholar crosses the courtyard at dawn.",
        subject="the scholar",
    )
    assert contract["executed_here"] is False
    assert contract["verified_by_hevi_render"] is False
    assert "Camera movement:" in contract["camera_clause"]
    assert "End:" in contract["camera_clause"]
    assert contract["scene_clause"] == "A scholar crosses the courtyard at dawn."
    assert contract["camera_clause"] not in contract["scene_clause"]
    assert contract["prompt"].startswith(contract["camera_clause"])
    assert contract["prompt"].endswith(contract["scene_clause"])


def test_b2_second_movement_in_scene_clause_and_unknown_id_raise():
    with pytest.raises(CapabilityError):
        b2.assemble_camera_clause(
            "dolly_in", scene_clause="then crane up over the roof"
        )
    with pytest.raises(CapabilityError):
        b2.assemble_camera_clause("no_such_move")
    with pytest.raises(CapabilityError):
        b2.assemble_camera_clause("")
