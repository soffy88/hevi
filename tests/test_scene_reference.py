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
