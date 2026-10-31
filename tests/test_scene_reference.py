"""Tests for pipeline.scene_reference (clean-room rewrite).

At least one positive and one negative case per grafted rule, plus
the ordering/budget branches, the empty-final and stale branches,
the Picture 1 note, and the single-definition lock on the
six-section format.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest

from hevi.capabilities import scene_reference as sr
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import get

BASE_PLAN = {
    "scene": {"description": "A quiet tea room.", "framing": "Fixed camera, wide shot."},
    "characters": [{"name": "Mei", "description": "A tea host in a plain robe."}],
    "angles": ["The same room from the doorway."],
    "shots": [{"description": "Rain runs down the window.",
               "dialogue": 'Mei says: "The rain has not stopped."'}],
    "soundscape": "Rain against the window, faint steam.",
    "voices": ["Mei"],
}


def test_build_produces_six_sections_in_order():
    built = sr.build_h3_prompt(BASE_PLAN)
    assert list(built["sections"]) == list(sr.H3_SECTIONS)
    assert sr.PICTURE_1_NOTE in built["text"]
    assert "fully_preserved" in built["sections"]["retention_analysis"]
    assert built["picture_refs"] == 3
    assert "Mei (S1) says, <d>The rain has not stopped.</d>" in built["text"]
    assert sr.check_h3_prompt(built)["verdict"] == "pass"
    assert sr.check_h3_prompt(built["text"])["verdict"] == "pass"


def test_build_missing_required_input_raises_and_invents_nothing():
    plan = dict(BASE_PLAN)
    plan.pop("soundscape")
    with pytest.raises(CapabilityError):
        sr.build_h3_prompt(plan)
    plan = dict(BASE_PLAN)
    plan.pop("shots")
    with pytest.raises(CapabilityError):
        sr.build_h3_prompt(plan)


def test_build_picture_cap_raises():
    plan = dict(BASE_PLAN)
    plan["characters"] = [
        {"name": f"C{i}", "description": "A guest."} for i in range(8)]
    with pytest.raises(CapabilityError):
        sr.build_h3_prompt(plan)


def test_build_voice_cap_raises():
    plan = dict(BASE_PLAN)
    plan["voices"] = ["A", "B", "C", "D"]
    with pytest.raises(CapabilityError):
        sr.build_h3_prompt(plan)


def test_build_undeclared_dialogue_speaker_raises():
    plan = dict(BASE_PLAN)
    plan["voices"] = []
    with pytest.raises(CapabilityError):
        sr.build_h3_prompt(plan)


def test_check_prompt_missing_section_and_note_fail():
    result = sr.check_h3_prompt("summary:\nA shot.\n")
    codes = {i["code"] for i in result["issues"]}
    assert result["verdict"] == "fail"
    assert "MISSING_SECTION" in codes
    assert "MISSING_PICTURE_1_NOTE" in codes


def test_check_prompt_out_of_order_fails():
    built = sr.build_h3_prompt(BASE_PLAN)
    lines = built["text"].split("\n\n")
    shuffled = "\n\n".join(reversed(lines))
    assert sr.check_h3_prompt(shuffled)["verdict"] == "fail"


def test_dialogue_rewrite_numbers_speakers_by_first_appearance():
    text, speakers = sr.rewrite_dialogue(
        'A says: "One." B says: "Two." A says: "Three."')
    assert speakers == ["A", "B"]
    assert "A (S1) says, <d>One.</d>" in text
    assert "B (S2) says, <d>Two.</d>" in text
    assert "A (S1) says, <d>Three.</d>" in text


def test_dialogue_already_tagged_left_alone():
    text, _ = sr.rewrite_dialogue("Mei (S1) says, <d>Rain.</d>")
    assert text == "Mei (S1) says, <d>Rain.</d>"


# ---------------------------------------------------------------- assembly

def _assembly():
    return {"references": [
        {"ref_id": "pic1", "kind": "scene", "picture": 1, "purpose": "place and framing"},
        {"ref_id": "pic2", "kind": "angle", "picture": 2, "purpose": "same room from doorway"},
        {"ref_id": "pic3", "kind": "cast", "picture": 3, "purpose": "Mei, tea host", "voice": True},
    ]}


def test_assembly_passes_in_order():
    result = sr.check_reference_assembly(_assembly())
    assert result["verdict"] == "pass"
    assert result["picture_count"] == 3
    assert result["voice_count"] == 1


def test_assembly_wrong_order_fails():
    assembly = _assembly()
    assembly["references"] = list(reversed(assembly["references"]))
    result = sr.check_reference_assembly(assembly)
    assert result["verdict"] == "fail"
    assert any(i["code"] == "REFERENCE_ORDER" for i in result["issues"])


def test_assembly_scene_not_picture_1_fails():
    assembly = _assembly()
    assembly["references"][0]["picture"] = 2
    assert sr.check_reference_assembly(assembly)["verdict"] == "fail"


def test_assembly_picture_budget_fails():
    assembly = {"references": [
        {"ref_id": f"p{i}", "kind": "cast", "picture": i, "purpose": "guest"}
        for i in range(1, 11)]}
    assembly["references"][0] = {
        "ref_id": "p1", "kind": "scene", "picture": 1, "purpose": "place"}
    result = sr.check_reference_assembly(assembly)
    assert result["verdict"] == "fail"
    assert any(i["code"] == "PICTURE_BUDGET" for i in result["issues"])


def test_assembly_voice_budget_fails():
    assembly = _assembly()
    for ref in assembly["references"]:
        ref["voice"] = True
    assembly["references"].append(
        {"ref_id": "p4", "kind": "cast", "picture": 4, "purpose": "guest", "voice": True})
    result = sr.check_reference_assembly(assembly)
    assert result["verdict"] == "fail"
    assert any(i["code"] == "VOICE_BUDGET" for i in result["issues"])


def test_assembly_undeclared_purpose_is_pending_not_pass():
    assembly = _assembly()
    assembly["references"][2]["purpose"] = ""
    result = sr.check_reference_assembly(assembly)
    assert result["verdict"] == "pending"
    assert any(i["code"] == "UNDECLARED_REFERENCE" for i in result["issues"])


# ---------------------------------------------------------------- intent/final

def test_resolve_final_prefers_finished_text_never_intent():
    assert sr.resolve_final_prompt("make a video", "expanded text", "") == "expanded text"
    assert sr.resolve_final_prompt("make a video", "", "action text") == "action text"
    with pytest.raises(CapabilityError):
        sr.resolve_final_prompt("make a video", "", "  ")


def test_final_empty_fails():
    result = sr.check_final_prompt({"intent": "make a video", "final_text": ""})
    assert result["verdict"] == "fail"
    assert any(i["code"] == "EMPTY_FINAL_PROMPT" for i in result["issues"])


def test_final_from_intent_source_fails():
    result = sr.check_final_prompt(
        {"intent": "x", "final_text": "x", "final_source": "intent"})
    assert result["verdict"] == "fail"
    assert any(i["code"] == "INTENT_USED_AS_FINAL" for i in result["issues"])


def test_final_changed_since_review_is_stale():
    final = "A finished prompt."
    old_hash = hashlib.sha256(b"An older prompt.").hexdigest()
    result = sr.check_final_prompt(
        {"intent": "x", "final_text": final, "previous_final_hash": old_hash})
    assert result["verdict"] == "stale"
    assert any(i["code"] == "STALE_FINAL_PROMPT" for i in result["issues"])
    same_hash = hashlib.sha256(final.encode()).hexdigest()
    result = sr.check_final_prompt(
        {"intent": "x", "final_text": final, "previous_final_hash": same_hash})
    assert result["verdict"] == "pass"


def test_final_identical_to_intent_warns():
    result = sr.check_final_prompt({"intent": "same", "final_text": "same"})
    assert result["verdict"] == "pass"
    assert any(i["code"] == "FINAL_EQUALS_INTENT" for i in result["issues"])


# ---------------------------------------------------------------- combined

def test_combined_plan_passes():
    plan = {"build": BASE_PLAN, "assembly": _assembly(),
            "final": {"intent": "tea room", "final_text": "A finished prompt."}}
    result = sr.check_scene_reference(plan)
    assert result["verdict"] == "pass"


def test_combined_plan_fails_on_empty_final():
    plan = {"build": BASE_PLAN, "assembly": _assembly(),
            "final": {"intent": "tea room", "final_text": ""}}
    assert sr.check_scene_reference(plan)["verdict"] == "fail"


def test_format_defined_in_exactly_one_capabilities_module():
    root = Path(sr.__file__).resolve().parent
    # A module counts as defining the format only when it names all
    # six sections: single shared words such as "summary" appear
    # elsewhere and do not constitute a second definition.
    pattern = re.compile(r'"(subject_definitions|summary|retention_analysis|'
                         r'detailed_description|overall_soundscape|'
                         r'non_diegetic_music)"')
    defining = []
    for path in sorted(root.glob("*.py")):
        names = set(pattern.findall(path.read_text(encoding="utf-8")))
        if names == set(sr.H3_SECTIONS):
            defining.append(path.name)
    assert defining == ["scene_reference.py"], defining


def test_capability_registered():
    assert get("pipeline.scene_reference") is not None


# ---------------------------------------------------------------- P1: photo scene

def _photo_record(**overrides):
    record = {
        "main_view": "main.jpg",
        "angles": [
            {"ref_id": "door.jpg", "description": "The same room from the doorway."},
            {"ref_id": "window.jpg", "description": "The same room from the window."},
        ],
        "place_description": "A quiet tea room with a wooden floor and low light.",
        "create": "movie",
    }
    record.update(overrides)
    return record


def test_photo_scene_movie_passes_and_applies_angles():
    result = sr.check_photo_scene(_photo_record())
    assert result["verdict"] == "pass"
    assert result["main_view"] == "main.jpg"
    assert result["angle_count"] == 2
    assert result["angles_applied"] is True
    assert result["angles_for_movie"] == 2


def test_photo_scene_image_without_angles_passes():
    result = sr.check_photo_scene(
        _photo_record(angles=[], create="image"))
    assert result["verdict"] == "pass"
    assert result["angles_applied"] is False


def test_photo_scene_no_main_view_fails():
    result = sr.check_photo_scene(
        {"angles": [{"ref_id": "a.jpg", "description": "From the door."}],
         "place_description": "A tea room."})
    assert result["verdict"] == "fail"
    assert any(i["code"] == "NO_MAIN_VIEW" for i in result["issues"])


def test_photo_scene_multiple_mains_fail():
    result = sr.check_photo_scene({"pictures": [
        {"ref_id": "a.jpg", "role": "main"},
        {"ref_id": "b.jpg", "role": "main"},
    ], "place_description": "A tea room."})
    assert result["verdict"] == "fail"
    assert any(i["code"] == "MULTIPLE_MAIN_VIEWS" for i in result["issues"])


def test_photo_scene_main_not_first_fails():
    result = sr.check_photo_scene({"pictures": [
        {"ref_id": "a.jpg", "role": "angle", "description": "From the door."},
        {"ref_id": "b.jpg", "role": "main"},
    ], "place_description": "A tea room."})
    assert result["verdict"] == "fail"
    assert any(i["code"] == "MAIN_VIEW_NOT_FIRST" for i in result["issues"])


def test_photo_scene_angle_without_description_is_pending():
    record = _photo_record()
    record["angles"] = [{"ref_id": "door.jpg", "description": ""}]
    result = sr.check_photo_scene(record)
    assert result["verdict"] == "pending"
    assert any(i["code"] == "ANGLE_WITHOUT_DESCRIPTION" for i in result["issues"])


def test_photo_scene_angle_cap_fails():
    record = _photo_record()
    record["angles"] = [
        {"ref_id": f"a{i}.jpg", "description": "Another angle."} for i in range(5)]
    result = sr.check_photo_scene(record)
    assert result["verdict"] == "fail"
    assert any(i["code"] == "ANGLE_CAP" for i in result["issues"])


def test_photo_scene_image_with_angles_warns_and_does_not_apply():
    result = sr.check_photo_scene(_photo_record(create="image"))
    assert result["verdict"] == "pass"
    assert result["angles_applied"] is False
    assert any(i["code"] == "ANGLES_NOT_APPLIED_TO_IMAGE" for i in result["issues"])


def test_photo_scene_angles_in_pictures_warns_about_camera_risk():
    result = sr.check_photo_scene(
        _photo_record(create="image", angles_in_pictures=True))
    assert result["verdict"] == "pass"
    assert result["angles_applied"] is True
    assert any(i["code"] == "ANGLES_IN_PICTURES_RISK" for i in result["issues"])


def test_photo_scene_missing_place_description_is_pending():
    record = _photo_record()
    record.pop("place_description")
    result = sr.check_photo_scene(record)
    assert result["verdict"] == "pending"
    assert any(i["code"] == "PLACE_DESCRIPTION_MISSING" for i in result["issues"])


def test_photo_scene_place_describing_people_fails():
    result = sr.check_photo_scene(
        _photo_record(place_description="A tea room where a man stands by the window."))
    assert result["verdict"] == "fail"
    assert any(i["code"] == "PLACE_DESCRIPTION_CONTENT" for i in result["issues"])


def test_photo_scene_place_commenting_on_photo_quality_fails():
    result = sr.check_photo_scene(
        _photo_record(place_description="A blurry photo of a tea room, poor quality."))
    assert result["verdict"] == "fail"
    assert any(i["code"] == "PLACE_DESCRIPTION_CONTENT" for i in result["issues"])


# ---------------------------------------------------------------- P1: blocking

def _blocking_record(**overrides):
    record = {
        "cast": ["Mei"],
        "markers": [{
            "marker_id": "m1", "character": "Mei",
            "screen_zone": "left", "depth": "foreground",
            "camera_relation": "facing_camera",
            "view": "body_front", "visible_parts": ["face", "upper_clothing"],
            "placeholder_not_in_film": True,
        }],
    }
    record.update(overrides)
    return record


def test_blocking_passes_and_reuses_character_sheet_tables():
    from hevi.capabilities import character_sheet as cs

    assert sr.DEFAULT_PART_TABLE is cs.DEFAULT_PART_TABLE
    result = sr.check_blocking(_blocking_record())
    assert result["verdict"] == "pass"
    assert result["markers"][0]["bound_to"] == "Mei"
    assert result["markers"][0]["distinct_from_cast"] is False


def test_blocking_missing_placeholder_declaration_fails():
    record = _blocking_record()
    record["markers"][0].pop("placeholder_not_in_film")
    result = sr.check_blocking(record)
    assert result["verdict"] == "fail"
    assert any(i["code"] == "MISSING_PLACEHOLDER_DECLARATION" for i in result["issues"])


def test_blocking_unbound_marker_is_recorded_as_distinct_not_failed():
    record = _blocking_record()
    record["markers"][0].pop("character")
    result = sr.check_blocking(record)
    assert result["verdict"] == "pass"
    assert result["markers"][0]["distinct_from_cast"] is True
    assert any(i["code"] == "UNBOUND_MARKER" for i in result["issues"])


def test_blocking_unknown_character_fails_and_names_marker():
    record = _blocking_record()
    record["markers"][0]["character"] = "NoSuchPerson"
    result = sr.check_blocking(record)
    assert result["verdict"] == "fail"
    issue = next(i for i in result["issues"]
                 if i["code"] == "UNKNOWN_BLOCKING_CHARACTER")
    assert "m1" in issue["message"] and "NoSuchPerson" in issue["message"]


def test_blocking_face_in_rear_view_fails():
    record = _blocking_record()
    marker = record["markers"][0]
    marker.update({"camera_relation": "back_to_camera", "view": "body_back",
                   "visible_parts": ["face"]})
    result = sr.check_blocking(record)
    assert result["verdict"] == "fail"
    issue = next(i for i in result["issues"]
                 if i["code"] == "BLOCKING_FACE_IN_REAR_VIEW")
    assert "m1" in issue["message"] and "body_back" in issue["message"]


def test_blocking_part_out_of_view_scope_fails():
    record = _blocking_record()
    marker = record["markers"][0]
    marker.update({"view": "face_front", "visible_parts": ["footwear"]})
    result = sr.check_blocking(record)
    assert result["verdict"] == "fail"
    issue = next(i for i in result["issues"]
                 if i["code"] == "BLOCKING_PART_SCOPE")
    assert "footwear" in issue["message"] and "face_front" in issue["message"]


def test_blocking_view_relation_conflict_fails():
    record = _blocking_record()
    marker = record["markers"][0]
    marker.update({"camera_relation": "back_to_camera", "view": "body_front",
                   "visible_parts": ["upper_clothing"]})
    result = sr.check_blocking(record)
    assert result["verdict"] == "fail"
    assert any(i["code"] == "BLOCKING_VIEW_RELATION_CONFLICT"
               for i in result["issues"])


def test_blocking_view_not_in_sheet_fails():
    record = _blocking_record(character_sheet={"views": ["body_front"]})
    marker = record["markers"][0]
    marker.update({"camera_relation": "back_to_camera", "view": "body_back",
                   "visible_parts": ["back_clothing"]})
    result = sr.check_blocking(record)
    assert result["verdict"] == "fail"
    assert any(i["code"] == "BLOCKING_VIEW_NOT_IN_SHEET"
               for i in result["issues"])


def test_blocking_duplicate_marker_and_unknown_zone_fail():
    record = _blocking_record()
    record["markers"].append(dict(record["markers"][0]))
    record["markers"][1]["screen_zone"] = "middle"
    result = sr.check_blocking(record)
    codes = {i["code"] for i in result["issues"]}
    assert result["verdict"] == "fail"
    assert "DUPLICATE_MARKER" in codes
    assert "UNKNOWN_SCREEN_ZONE" in codes


# ---------------------------------------------------------------- P1: output precheck

def test_frame_count_lattice():
    assert sr.h3_frame_count(5) == 124
    assert sr.h3_frame_count(5.0, 24) == 124
    assert sr.h3_frame_count(0.1) == 5
    assert sr.h3_frame_count(2) == 56
    assert sr.h3_frame_count(10) == 243
    with pytest.raises(CapabilityError):
        sr.h3_frame_count(0)
    with pytest.raises(CapabilityError):
        sr.h3_frame_count(-1)


def test_output_size_snaps_to_grid_at_target_area():
    width, height = sr.h3_output_size(1920, 1080)
    assert (width, height) == (832, 480)
    assert width % 32 == 0 and height % 32 == 0
    with pytest.raises(CapabilityError):
        sr.h3_output_size(0, 1080)


def test_output_plan_passes_without_crop():
    result = sr.check_output_plan(
        {"seconds": 5, "source_width": 1920, "source_height": 1080})
    assert result["verdict"] == "pass"
    assert result["frames"] == 124
    assert result["frame_seconds"] == pytest.approx(124 / 24)
    assert (result["output_width"], result["output_height"]) == (832, 480)
    assert result["cropped"] is False


def test_output_plan_requested_frames_off_lattice_fails():
    result = sr.check_output_plan(
        {"seconds": 5, "requested_frames": 120,
         "source_width": 1920, "source_height": 1080})
    assert result["verdict"] == "fail"
    assert any(i["code"] == "REQUESTED_FRAMES_OFF_LATTICE"
               for i in result["issues"])
    alone = sr.check_output_plan(
        {"requested_frames": 124, "source_width": 1920, "source_height": 1080})
    assert alone["verdict"] == "pass" and alone["frames"] == 124
    off = sr.check_output_plan(
        {"requested_frames": 120, "source_width": 1920, "source_height": 1080})
    assert off["verdict"] == "fail"


def test_output_plan_undeclared_aspect_crop_fails_and_declared_passes():
    plan = {"seconds": 5, "source_width": 1920, "source_height": 1080,
            "target_aspect": "9:16"}
    result = sr.check_output_plan(plan)
    assert result["verdict"] == "fail"
    assert any(i["code"] == "UNDECLARED_CROP" for i in result["issues"])
    declared = sr.check_output_plan({**plan, "crop_declared": True})
    assert declared["verdict"] == "pass"
    assert declared["cropped"] is True
    assert (declared["crop"]["width"], declared["crop"]["height"]) == (592, 1080)
    assert (declared["output_width"], declared["output_height"]) == (480, 864)


def test_output_plan_undeclared_delivery_crop_fails_and_declared_passes():
    plan = {"seconds": 5, "source_width": 1920, "source_height": 1080,
            "delivery_frames": 120}
    result = sr.check_output_plan(plan)
    assert result["verdict"] == "fail"
    assert any(i["code"] == "UNDECLARED_DELIVERY_CROP" for i in result["issues"])
    declared = sr.check_output_plan({**plan, "delivery_crop_declared": True})
    assert declared["verdict"] == "pass"
    assert declared["delivery_frames"] == 120


def test_output_plan_malformed_duration_raises():
    with pytest.raises(CapabilityError):
        sr.check_output_plan({"source_width": 1920, "source_height": 1080})
    with pytest.raises(CapabilityError):
        sr.check_output_plan({"seconds": 0, "source_width": 1920,
                              "source_height": 1080})


# ---------------------------------------------------------------- P1: combined

def test_combined_plan_with_p1_sections_passes_and_reports_them():
    plan = {"build": BASE_PLAN, "assembly": _assembly(),
            "final": {"intent": "tea room", "final_text": "A finished prompt."},
            "photo_scene": _photo_record(),
            "blocking": _blocking_record(),
            "output": {"seconds": 5, "source_width": 1920, "source_height": 1080}}
    result = sr.check_scene_reference(plan)
    assert result["verdict"] == "pass"
    assert result["photo_scene"]["verdict"] == "pass"
    assert result["blocking"]["verdict"] == "pass"
    assert result["output"]["frames"] == 124


def test_combined_plan_fails_on_blocking_without_declaration():
    blocking = _blocking_record()
    blocking["markers"][0].pop("placeholder_not_in_film")
    plan = {"build": BASE_PLAN, "assembly": _assembly(),
            "final": {"intent": "tea room", "final_text": "A finished prompt."},
            "blocking": blocking}
    assert sr.check_scene_reference(plan)["verdict"] == "fail"
