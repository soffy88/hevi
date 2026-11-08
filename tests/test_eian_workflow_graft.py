"""Tests for the Eian workflow graft (A1-A9 gates, B1-B4 fake contracts)."""

import pytest

from hevi.capabilities import blind_review_gate as a6
from hevi.capabilities import character_sheet_schema as b4
from hevi.capabilities import final_film_review_gate as a7
from hevi.capabilities import first_last_frame_check_gate as a3
from hevi.capabilities import four_thread_contract as b2
from hevi.capabilities import list_capabilities
from hevi.capabilities import model_error_table_gate as a5
from hevi.capabilities import paid_generation_economy_gate as a8
from hevi.capabilities import palette_table_schema as b3
from hevi.capabilities import reference_frame_measure_gate as a9
from hevi.capabilities import seedance_task_schema as b1
from hevi.capabilities import seven_section_prompt_gate as a4
from hevi.capabilities import shotlist_six_rule_gate as a2
from hevi.capabilities import story_five_standard_gate as a1
from hevi.capabilities.errors import CapabilityError

EXPECTED_NAMES = {
    "qa.story_five_standard_gate",
    "qa.shotlist_six_rule_gate",
    "qa.first_last_frame_check_gate",
    "qa.seven_section_prompt_gate",
    "qa.model_error_table_gate",
    "qa.blind_review_gate",
    "qa.final_film_review_gate",
    "qa.paid_generation_economy_gate",
    "qa.reference_frame_measure_gate",
    "video.seedance_task_schema",
    "video.four_thread_contract",
    "video.palette_table_schema",
    "video.character_sheet_schema",
}


def test_all_thirteen_registered() -> None:
    names = {c.name for c in list_capabilities()}
    assert names >= EXPECTED_NAMES


# --- A1: story five standards ---


def _a1_story(**overrides):
    story = {
        "one_line_theme": "A boy asks what the first thing in life is.",
        "hook": {"second": 2, "image": "A boy looks up at his teacher"},
        "structure": "episodic",
        "bystander_reactions": [
            {"beat": "question", "actor": "teacher", "reaction": "pauses", "delay_s": 0},
            {"beat": "question", "actor": "classmate", "reaction": "turns around", "delay_s": 1},
        ],
        "weak_points": ["small_object_in_hand"],
        "avoid_notes": {"small_object_in_hand": "the cup stays on the desk all shot"},
    }
    story.update(overrides)
    return story


def test_a1_full_story_passes() -> None:
    report = a1.check_story_five_standards(_a1_story())
    assert report["verdict"] == "pass"
    assert report["executed_here"] is False


def test_a1_missing_theme_fails() -> None:
    report = a1.check_story_five_standards(_a1_story(one_line_theme=""))
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "theme_missing"


def test_a1_simultaneous_reaction_fails() -> None:
    story = _a1_story(
        bystander_reactions=[
            {"beat": "question", "actor": "teacher", "reaction": "pauses", "delay_s": 0},
            {"beat": "question", "actor": "classmate", "reaction": "turns", "delay_s": 0},
        ]
    )
    report = a1.check_story_five_standards(story)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "simultaneous_reaction"


def test_a1_unmitigated_weak_point_fails() -> None:
    story = _a1_story(weak_points=["mirror_reflection"], avoid_notes={})
    report = a1.check_story_five_standards(story)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "unmitigated_weak_point"


def test_a1_continuous_without_links_fails() -> None:
    story = _a1_story(structure="continuous")
    report = a1.check_story_five_standards(story)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "continuity_unexplained"


def test_a1_continuous_with_links_passes() -> None:
    story = _a1_story(
        structure="continuous",
        continuity_links=["the letter carries over to the next scene"],
    )
    assert a1.check_story_five_standards(story)["verdict"] == "pass"


def test_a1_non_object_fails() -> None:
    report = a1.check_story_five_standards("not a story")
    assert report["verdict"] == "fail"


# --- A2: shotlist six rules ---


def _a2_shot(**overrides):
    shot = {
        "angle": "low_angle",
        "size": "full",
        "moving_subject": "the boy walks in from the left",
        "camera_reason": "follow the boy to the desk",
        "subject_x_percent": 38,
    }
    shot.update(overrides)
    return shot


def _a2_shotlist(**overrides):
    shotlist = {
        "shots": [
            _a2_shot(size="full", angle="low_angle"),
            _a2_shot(size="half", angle="over_shoulder"),
            _a2_shot(size="close_up", angle="high_angle"),
        ],
        "palette_table": {"classroom": {"wall": "warm beige", "desk": "dark wood"}},
        "bw_check": {"readable": True},
    }
    shotlist.update(overrides)
    return shotlist


def test_a2_full_shotlist_passes() -> None:
    report = a2.check_shotlist_six_rules(_a2_shotlist())
    assert report["verdict"] == "pass"
    assert report["executed_here"] is False


def test_a2_three_same_size_fails() -> None:
    shotlist = _a2_shotlist(
        shots=[_a2_shot(size="full"), _a2_shot(size="full"), _a2_shot(size="full")]
    )
    report = a2.check_shotlist_six_rules(shotlist)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "same_size_run"


def test_a2_nothing_moves_fails() -> None:
    shotlist = _a2_shotlist(shots=[_a2_shot(moving_subject="")])
    report = a2.check_shotlist_six_rules(shotlist)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "nothing_moves"


def test_a2_too_many_frontal_fails() -> None:
    shotlist = _a2_shotlist(
        shots=[
            _a2_shot(angle="eye_level_frontal", size="full"),
            _a2_shot(angle="eye_level_frontal", size="half"),
            _a2_shot(angle="eye_level_frontal", size="close_up"),
        ]
    )
    report = a2.check_shotlist_six_rules(shotlist)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "too_many_frontal"


def test_a2_off_golden_ratio_fails() -> None:
    shotlist = _a2_shotlist(shots=[_a2_shot(subject_x_percent=50)])
    report = a2.check_shotlist_six_rules(shotlist)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "off_golden_ratio"


def test_a2_no_palette_fails() -> None:
    shotlist = _a2_shotlist(palette_table={})
    report = a2.check_shotlist_six_rules(shotlist)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "palette_missing"


def test_a2_bw_unreadable_without_note_fails() -> None:
    shotlist = _a2_shotlist(bw_check={"readable": False})
    report = a2.check_shotlist_six_rules(shotlist)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "bw_unreadable_ungraded"


def test_a2_bw_unreadable_with_note_passes() -> None:
    shotlist = _a2_shotlist(
        bw_check={"readable": False, "regrade_note": "raise wall brightness by 10%"}
    )
    assert a2.check_shotlist_six_rules(shotlist)["verdict"] == "pass"


# --- A3: first/last-frame checks ---


def _a3_shot(**overrides):
    shot = {
        "props_needed": ["cup", "letter"],
        "props_in_first": ["cup", "letter", "desk"],
        "bystanders": [{"actor": "teacher", "facing_camera": True}],
        "poses": ["standing", "leaning"],
        "wind_directions": {"scarf": "left", "sheet": "left"},
        "extra_objects": [],
        "overlay_alignment": {"aligned": True, "changed_regions": []},
        "mobile_check": {"checked": True, "distant_figure_readable": True},
    }
    shot.update(overrides)
    return shot


def test_a3_full_shot_passes() -> None:
    report = a3.check_first_last_frame(_a3_shot())
    assert report["verdict"] == "pass"
    assert report["executed_here"] is False


def test_a3_missing_prop_fails() -> None:
    report = a3.check_first_last_frame(_a3_shot(props_in_first=["desk"]))
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "prop_appears_from_nowhere"


def test_a3_reaction_not_staged_fails() -> None:
    shot = _a3_shot(bystanders=[{"actor": "teacher", "facing_camera": False}])
    report = a3.check_first_last_frame(shot)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "reaction_not_staged"


def test_a3_same_pose_fails() -> None:
    report = a3.check_first_last_frame(_a3_shot(poses=["standing", "standing"]))
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "same_pose_group"


def test_a3_wind_inconsistent_fails() -> None:
    shot = _a3_shot(wind_directions={"scarf": "left", "sheet": "right"})
    report = a3.check_first_last_frame(shot)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "wind_inconsistent"


def test_a3_frozen_region_changed_fails() -> None:
    shot = _a3_shot(overlay_alignment={"aligned": True, "changed_regions": ["wall_color"]})
    report = a3.check_first_last_frame(shot)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "frozen_region_changed"


def test_a3_extra_objects_fails() -> None:
    report = a3.check_first_last_frame(_a3_shot(extra_objects=["stray kettle"]))
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "extra_objects"


# --- A4: seven-section prompt ---


def _a4_prompt(**overrides):
    prompt = {
        "style": "clean modern 2D hand-drawn animation",
        "camera": "eye-level, slow push in",
        "composition_palette": "warm beige walls, dark wood desk",
        "characters": [
            {
                "look": "boy with black hair",
                "outfit": "blue robe",
                "fixed_props": ["letter in right hand"],
            }
        ],
        "per_second": [
            {"start_s": 0, "end_s": 0.2, "action": "hold still", "hold": True},
            {"start_s": 0.2, "end_s": 4.7, "action": "the boy walks left"},
            {"start_s": 4.7, "end_s": 5.0, "action": "hold still", "hold_tail": True},
        ],
        "duration_s": 5.0,
        "sound": {"audible": [{"sound": "footsteps", "visible_cause": True}]},
        "constraints": {"no_text": True, "no_watermark": True, "single_take": True},
    }
    prompt.update(overrides)
    return prompt


def test_a4_full_prompt_passes() -> None:
    report = a4.check_seven_section_prompt(_a4_prompt())
    assert report["verdict"] == "pass"
    assert report["executed_here"] is False


def test_a4_missing_section_fails() -> None:
    prompt = _a4_prompt()
    del prompt["sound"]
    report = a4.check_seven_section_prompt(prompt)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "section_missing"


def test_a4_opening_not_frozen_fails() -> None:
    prompt = _a4_prompt(
        per_second=[
            {"start_s": 0, "end_s": 0.2, "action": "walks in"},
            {"start_s": 0.2, "end_s": 4.7, "action": "the boy walks left"},
            {"start_s": 4.7, "end_s": 5.0, "action": "hold still", "hold_tail": True},
        ]
    )
    report = a4.check_seven_section_prompt(prompt)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "opening_not_frozen"


def test_a4_ending_not_frozen_fails() -> None:
    prompt = _a4_prompt(
        per_second=[
            {"start_s": 0, "end_s": 0.2, "action": "hold still", "hold": True},
            {"start_s": 0.2, "end_s": 4.7, "action": "the boy walks left"},
            {"start_s": 4.7, "end_s": 5.0, "action": "walks away"},
        ]
    )
    report = a4.check_seven_section_prompt(prompt)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "ending_not_frozen"


def test_a4_character_not_locked_fails() -> None:
    prompt = _a4_prompt(characters=[{"look": "boy", "outfit": "", "fixed_props": ["letter"]}])
    report = a4.check_seven_section_prompt(prompt)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "character_not_locked"


def test_a4_sound_without_visible_cause_fails() -> None:
    prompt = _a4_prompt(sound={"audible": [{"sound": "music", "visible_cause": False}]})
    report = a4.check_seven_section_prompt(prompt)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "sound_without_visible_cause"


def test_a4_text_not_banned_fails() -> None:
    prompt = _a4_prompt(constraints={"no_text": False, "no_watermark": True})
    report = a4.check_seven_section_prompt(prompt)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "constraint_text_not_banned"


# --- A5: model error table ---


def _a5_prompt(**overrides):
    prompt = {
        "lines": [
            "The father picks up the letter first.",
            "One second later the grandmother reaches for it.",
        ],
        "positive_rewrites": [],
        "actions": [
            {"actor": "father", "action": "pick up letter", "delay_s": 0, "prop": "letter"},
            {"actor": "grandmother", "action": "reach for letter", "delay_s": 1},
        ],
        "first_frame_items": ["letter", "desk"],
        "counts_declared": {"letter": 1},
        "counts_in_frame": {"letter": 1},
    }
    prompt.update(overrides)
    return prompt


def test_a5_clean_prompt_passes() -> None:
    report = a5.check_model_error_table(_a5_prompt())
    assert report["verdict"] == "pass"
    assert report["executed_here"] is False


def test_a5_negation_without_rewrite_fails() -> None:
    prompt = _a5_prompt(lines=["Do not let the kettle pour water."])
    report = a5.check_model_error_table(prompt)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "negation_without_positive_rewrite"


def test_a5_negation_with_rewrite_passes() -> None:
    prompt = _a5_prompt(
        lines=["Do not let the kettle pour water."],
        positive_rewrites=[
            {
                "line": "Do not let the kettle pour water.",
                "rewrite": "The kettle stays on the shelf.",
            }
        ],
    )
    assert a5.check_model_error_table(prompt)["verdict"] == "pass"


def test_a5_simultaneous_action_fails() -> None:
    prompt = _a5_prompt(
        actions=[
            {"actor": "father", "action": "raise hand", "delay_s": 0},
            {"actor": "grandmother", "action": "raise hand", "delay_s": 0},
        ]
    )
    report = a5.check_model_error_table(prompt)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "simultaneous_action"


def test_a5_count_mismatch_fails() -> None:
    prompt = _a5_prompt(counts_in_frame={"letter": 2})
    report = a5.check_model_error_table(prompt)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "count_mismatch"


def test_a5_prop_not_in_first_frame_fails() -> None:
    prompt = _a5_prompt(
        actions=[{"actor": "father", "action": "pick up cup", "delay_s": 0, "prop": "cup"}]
    )
    report = a5.check_model_error_table(prompt)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "prop_not_in_first_frame"


def test_a5_too_many_actions_fails() -> None:
    prompt = _a5_prompt(
        actions=[
            {"actor": "father", "action": "stand up", "delay_s": 0},
            {"actor": "father", "action": "walk left", "delay_s": 1},
            {"actor": "father", "action": "open the door", "delay_s": 2},
        ]
    )
    report = a5.check_model_error_table(prompt)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "too_many_main_actions"


# --- A6: blind review ---


def _a6_review(**overrides):
    review = {
        "materials": {
            "prompt_file": "prompt.txt",
            "first_frame": "first.png",
            "last_frame": "last.png",
            "setting_sheet": "setting.md",
            "shotlist": "shots.md",
            "palette_rules": "palette.md",
        },
        "files_modified": False,
        "conclusions_given": False,
        "verdict": "pass",
        "findings": [],
    }
    review.update(overrides)
    return review


def test_a6_clean_review_passes() -> None:
    report = a6.check_blind_review(_a6_review())
    assert report["verdict"] == "pass"
    assert report["executed_here"] is False


def test_a6_modified_files_fails() -> None:
    report = a6.check_blind_review(_a6_review(files_modified=True))
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "reviewer_modified_files"


def test_a6_conclusions_given_fails() -> None:
    report = a6.check_blind_review(_a6_review(conclusions_given=True))
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "conclusions_given"


def test_a6_missing_material_fails() -> None:
    review = _a6_review()
    del review["materials"]["last_frame"]
    report = a6.check_blind_review(review)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "materials_incomplete"


def test_a6_no_pass_no_submit() -> None:
    report = a6.check_blind_review(_a6_review(verdict="fail"))
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "review_not_passed"


# --- A7: final-film review ---


def _a7_review(**overrides):
    review = {
        "film_file": "film.mp4",
        "story_understood": "A boy asks his teacher a question.",
        "unclear_points": [],
        "uncheckable": ["feel of the motion", "sound"],
        "cut_frames_checked": True,
        "findings": [{"time_s": 12.5, "frame": 375, "issue": "colour shift", "severity": "minor"}],
        "verdict": "pass",
    }
    review.update(overrides)
    return review


def test_a7_clean_review_passes() -> None:
    report = a7.check_final_film_review(_a7_review())
    assert report["verdict"] == "pass"
    assert report["executed_here"] is False


def test_a7_hard_issue_under_pass_fails() -> None:
    review = _a7_review(
        findings=[{"time_s": 3.0, "frame": 90, "issue": "face warps", "severity": "hard"}]
    )
    report = a7.check_final_film_review(review)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "hard_issues_unresolved"


def test_a7_ungraded_severity_fails() -> None:
    review = _a7_review(
        findings=[{"time_s": 3.0, "frame": 90, "issue": "face warps", "severity": "bad"}]
    )
    report = a7.check_final_film_review(review)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "severity_ungraded"


def test_a7_uncheckable_missing_fails() -> None:
    report = a7.check_final_film_review(_a7_review(uncheckable=[]))
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "uncheckable_not_declared"


def test_a7_cut_frames_not_checked_fails() -> None:
    report = a7.check_final_film_review(_a7_review(cut_frames_checked=False))
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "cut_frames_not_checked"


# --- A8: paid-generation economy ---


def _a8_plan(**overrides):
    plan = {
        "model": "doubao-seedance-2-0-mini-260615",
        "pricing": {"unit": "cny_per_million_tokens", "rate": 23},
        "budget": {"currency": "CNY", "amount": 200, "approved": True},
        "resolution": "720p",
        "upscale_to": "1080p",
        "hardest_first": True,
        "balance_check": {"balance_ok": True},
        "retakes": [{"reason": "hand warps", "changed_prompt_or_frames": True, "kept_old": True}],
    }
    plan.update(overrides)
    return plan


def test_a8_mini_plan_passes() -> None:
    report = a8.check_paid_generation_economy(_a8_plan())
    assert report["verdict"] == "pass"
    assert report["executed_here"] is False


def test_a8_2_5_rate_passes() -> None:
    plan = _a8_plan(
        model="doubao-seedance-2-5-260628",
        pricing={"unit": "cny_per_million_tokens", "rate": 70},
    )
    assert a8.check_paid_generation_economy(plan)["verdict"] == "pass"


def test_a8_per_second_pricing_fails() -> None:
    plan = _a8_plan(pricing={"unit": "cny_per_second", "rate": 0.5})
    report = a8.check_paid_generation_economy(plan)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "pricing_not_token_basis"


def test_a8_wrong_rate_fails() -> None:
    plan = _a8_plan(pricing={"unit": "cny_per_million_tokens", "rate": 70})
    report = a8.check_paid_generation_economy(plan)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "pricing_rate_mismatch"


def test_a8_budget_not_approved_fails() -> None:
    plan = _a8_plan(budget={"currency": "CNY", "amount": 200, "approved": False})
    report = a8.check_paid_generation_economy(plan)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "budget_not_approved"


def test_a8_retake_without_change_fails() -> None:
    plan = _a8_plan(
        retakes=[{"reason": "hand warps", "changed_prompt_or_frames": False, "kept_old": True}]
    )
    report = a8.check_paid_generation_economy(plan)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "retake_without_change"


def test_a8_old_segment_deleted_fails() -> None:
    plan = _a8_plan(
        retakes=[{"reason": "hand warps", "changed_prompt_or_frames": True, "kept_old": False}]
    )
    report = a8.check_paid_generation_economy(plan)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "old_segment_deleted"


def test_a8_insufficient_balance_fails() -> None:
    plan = _a8_plan(balance_check={"balance_ok": False})
    report = a8.check_paid_generation_economy(plan)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "insufficient_balance_stop"


# --- A9: reference-frame measurement ---


def _a9_study(**overrides):
    study = {
        "reference_film": "reference.mp4",
        "measurements": [{"shot": 1, "camera": "low angle push in", "entry_exit_ratio": 0.38}],
        "shots": [
            {"size": "full", "camera": "low angle", "movement": "push in", "direction": "left"}
        ],
    }
    study.update(overrides)
    return study


def test_a9_measured_reference_passes() -> None:
    report = a9.check_reference_frame_measure(_a9_study())
    assert report["verdict"] == "pass"
    assert report["executed_here"] is False


def test_a9_reference_not_measured_fails() -> None:
    report = a9.check_reference_frame_measure(_a9_study(measurements=[]))
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "reference_not_measured"


def test_a9_shot_language_incomplete_fails() -> None:
    study = _a9_study(shots=[{"size": "full", "camera": "low angle", "movement": "push in"}])
    report = a9.check_reference_frame_measure(study)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "shot_language_incomplete"


def test_a9_no_reference_with_rules_passes() -> None:
    study = _a9_study(reference_film=None, measurements=[], composed_from_rules=True)
    assert a9.check_reference_frame_measure(study)["verdict"] == "pass"


def test_a9_no_reference_no_rules_fails() -> None:
    study = _a9_study(reference_film=None, measurements=[], composed_from_rules=False)
    report = a9.check_reference_frame_measure(study)
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "no_reference_no_rules"


# --- B1: Seedance task schema ---


def _b1_plan(**overrides):
    plan = {
        "model": "doubao-seedance-2-0-mini-260615",
        "pricing": {"unit": "cny_per_million_tokens", "rate": 23},
        "resolution": "720p",
        "upscale_to": "1080p",
        "task": {"polling": "GET tasks/{id}"},
    }
    plan.update(overrides)
    return plan


def test_b1_contract_compiles() -> None:
    contract = b1.compile_seedance_task(_b1_plan())
    assert contract["executed_here"] is False
    assert contract["submitted"] is False
    assert contract["output_file"] is None
    assert contract["model"] == "doubao-seedance-2-0-mini-260615"


def test_b1_unknown_model_raises() -> None:
    with pytest.raises(CapabilityError):
        b1.compile_seedance_task(_b1_plan(model="seedance-9"))


def test_b1_per_second_pricing_raises() -> None:
    with pytest.raises(CapabilityError):
        b1.compile_seedance_task(_b1_plan(pricing={"unit": "cny_per_second", "rate": 0.5}))


def test_b1_embedded_key_raises() -> None:
    with pytest.raises(CapabilityError):
        b1.compile_seedance_task(_b1_plan(api_key="sk-secret"))


def test_b1_submitted_claim_raises() -> None:
    with pytest.raises(CapabilityError):
        b1.compile_seedance_task(_b1_plan(submitted=True))


# --- B2: four-thread contract ---


def _b2_plan(**overrides):
    plan = {
        "roles": {
            "lead": "maker",
            "reviewer": "checker",
            "supervisor": "ledger keeper",
            "agent": "decider",
        },
        "budget": {"currency": "CNY", "amount": 200},
        "decisions": [
            {"decision": "use mini for simple shots", "basis": "3x cheaper", "confidence": "high"}
        ],
        "mapping_only": True,
    }
    plan.update(overrides)
    return plan


def test_b2_contract_compiles() -> None:
    contract = b2.compile_four_thread_contract(_b2_plan())
    assert contract["executed_here"] is False
    assert contract["mapping_only"] is True
    assert contract["decision_count"] == 1


def test_b2_missing_role_raises() -> None:
    plan = _b2_plan()
    del plan["roles"]["agent"]
    with pytest.raises(CapabilityError):
        b2.compile_four_thread_contract(plan)


def test_b2_decision_without_basis_raises() -> None:
    plan = _b2_plan(decisions=[{"decision": "use mini", "basis": "", "confidence": "high"}])
    with pytest.raises(CapabilityError):
        b2.compile_four_thread_contract(plan)


def test_b2_equivalence_claim_raises() -> None:
    with pytest.raises(CapabilityError):
        b2.compile_four_thread_contract(_b2_plan(claims_equivalence=True))


def test_b2_submit_without_review_pass_raises() -> None:
    with pytest.raises(CapabilityError):
        b2.compile_four_thread_contract(_b2_plan(submitted=True, review_passed=False))


def test_b2_over_budget_submit_raises() -> None:
    with pytest.raises(CapabilityError):
        b2.compile_four_thread_contract(
            _b2_plan(submitted=True, review_passed=True, estimated_cost=250)
        )


# --- B3: palette table schema ---


def _b3_plan(**overrides):
    plan = {
        "scenes": [
            {"scene": "classroom", "colors": {"wall": "warm beige", "desk": "dark wood"}},
            {"scene": "street", "colors": {"sky": "pale blue", "road": "grey"}},
        ],
        "bw_check": {"readable": True},
    }
    plan.update(overrides)
    return plan


def test_b3_contract_compiles() -> None:
    contract = b3.compile_palette_table(_b3_plan())
    assert contract["executed_here"] is False
    assert contract["scene_count"] == 2
    assert contract["output_file"] is None


def test_b3_scene_without_colors_raises() -> None:
    plan = _b3_plan(scenes=[{"scene": "classroom", "colors": {}}])
    with pytest.raises(CapabilityError):
        b3.compile_palette_table(plan)


def test_b3_bw_unreadable_without_note_raises() -> None:
    plan = _b3_plan(bw_check={"readable": False})
    with pytest.raises(CapabilityError):
        b3.compile_palette_table(plan)


# --- B4: character sheet schema ---


def _b4_plan(**overrides):
    plan = {
        "character": "Xiaomiao",
        "views": {"front": "round face, black fringe", "side": "small hair buns"},
        "expressions": ["curious", "happy", "surprised"],
        "fixed_props": [
            {"item": "red bow", "position": "top of head"},
            {"item": "two buttons", "position": "front of dress"},
        ],
    }
    plan.update(overrides)
    return plan


def test_b4_contract_compiles() -> None:
    contract = b4.compile_character_sheet(_b4_plan())
    assert contract["executed_here"] is False
    assert contract["character"] == "Xiaomiao"
    assert contract["expression_count"] == 3
    assert contract["output_file"] is None


def test_b4_fixed_prop_without_position_raises() -> None:
    plan = _b4_plan(fixed_props=[{"item": "red bow", "position": ""}])
    with pytest.raises(CapabilityError):
        b4.compile_character_sheet(plan)


def test_b4_missing_expression_raises() -> None:
    with pytest.raises(CapabilityError):
        b4.compile_character_sheet(_b4_plan(expressions=[]))


def test_b4_embedded_image_raises() -> None:
    with pytest.raises(CapabilityError):
        b4.compile_character_sheet(_b4_plan(image_file="sheet.png"))
