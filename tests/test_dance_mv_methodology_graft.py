"""Tests for the dance MV methodology graft.

Every capability gets a positive case and at least one
negative case. The registration test asserts all
seventeen names are present exactly once. The schema
(B) tests assert fail-closed behaviour: ``compile_*``
returns a contract declaring ``executed_here`` false
and ``output_file`` None on a well-formed input, and
raises ``CapabilityError`` on any shape violation.
"""

from __future__ import annotations

import pytest

from hevi.capabilities.dance_action_chain_gate import check_dance_action_chain
from hevi.capabilities.dance_action_chain_schema import compile_dance_action_chain
from hevi.capabilities.dance_asset_prop_ledger_gate import (
    check_dance_asset_prop_ledger,
)
from hevi.capabilities.dance_camera_physical_gate import check_dance_camera_physical
from hevi.capabilities.dance_camera_shot_schema import compile_dance_camera_shot
from hevi.capabilities.dance_camera_sync_gate import check_dance_camera_sync
from hevi.capabilities.dance_generation_review_gate import (
    check_dance_generation_review,
)
from hevi.capabilities.dance_genre_grammar_gate import check_dance_genre_grammar
from hevi.capabilities.dance_h3_prompt_gate import check_dance_h3_prompt
from hevi.capabilities.dance_music_structure_gate import check_dance_music_structure
from hevi.capabilities.dance_mv_pack_format_gate import check_dance_mv_pack
from hevi.capabilities.dance_mv_prompt_pack_schema import compile_dance_mv_prompt_pack
from hevi.capabilities.dance_reference_role_gate import check_dance_reference_roles
from hevi.capabilities.dance_segment_card_schema import compile_dance_segment_card
from hevi.capabilities.dance_time_window_gate import check_dance_time_window
from hevi.capabilities.dance_transition_gate import check_dance_transitions
from hevi.capabilities.dance_transition_table_schema import (
    compile_dance_transition_table,
)
from hevi.capabilities.registry import CapabilityError


def _valid_music() -> dict:
    return {
        "bpm": 120.0,
        "beat_s": 0.5,
        "beats_per_bar": 4,
        "bar_s": 2.0,
        "bars_per_phrase": 4,
        "phrase_s": 8.0,
        "first_downbeat_offset_s": 0.52,
        "cuts_manifest": {"source": "cuts.json", "verified": True},
        "timecode_basis": "global",
        "total_duration_s": 16.52,
        "shots": [
            {"basis": "global", "start_s": 0.52, "end_s": 8.52},
            {"basis": "global", "start_s": 8.52, "end_s": 16.52},
        ],
    }


def _valid_reference() -> dict:
    return {
        "template": "four_modern",
        "roles": {
            "picture_1": "identity",
            "picture_2": "composition_camera",
            "picture_3": "path_route",
            "picture_4": "environment",
        },
        "priority": {
            "identity_source": "picture_1",
            "environment_source": "picture_4",
        },
    }


def _valid_assets() -> dict:
    return {
        "assets": [
            {
                "name": "red dress",
                "source": "picture_1",
                "changeable": ["fold"],
                "unchangeable": ["color"],
            }
        ],
        "props": [
            {
                "name": "paper umbrella",
                "source": "picture_1",
                "quantity": 1,
                "position": "right hand",
                "first_appearance": "segment_1",
                "last_appearance": "segment_3",
                "may_be_held": True,
                "may_persist_across_shots": True,
            }
        ],
        "added_props": [],
    }


def _valid_genre() -> dict:
    return {
        "primary_genre": "kpop",
        "fusion_genres": [],
        "moves": [
            {
                "name": "sharp formation change",
                "genre": "kpop",
                "detail": "the group shifts formation on the beat",
            },
            {
                "name": "body wave",
                "genre": "kpop",
                "detail": "a wave travels down the body",
            },
        ],
    }


def _valid_chain() -> dict:
    return {
        "layers": {
            "groove": "a steady bounce on the beat",
            "main_chain": {
                "start_state": "standing with feet together, arms low",
                "power_source": "the push from the left foot",
                "entry_path": "a step forward onto the left foot",
                "beat_progression": "power builds across two beats",
                "peak": "the jump at the top of the phrase",
                "inertia": "the dress keeps swinging after the turn",
                "recovery": "land low and settle on both feet",
                "body_cloth_physics": "cloth follows the body lag",
                "camera_geometry": "the camera tracks in from the front",
                "music_trigger": "the drum drop at the chorus",
            },
            "micro_accents": [{"beat": "off-beat 2", "detail": "a quick smile at the camera"}],
        },
        "steps": [
            "set the support and preload",
            "pass the power along",
            "arrive at the peak",
            "brake and recover",
            "leave an entry for the next chain",
        ],
        "entry_state": {"support_foot": "left", "direction": "forward"},
        "exit_state": {"support_foot": "both", "direction": "down"},
    }


def _valid_time() -> dict:
    return {
        "windows": [
            {
                "duration_s": 1.5,
                "actions": ["step turn", "arm sweep"],
                "hero": False,
            },
            {
                "duration_s": 2.0,
                "actions": ["hero jump spin"],
                "hero": True,
            },
        ],
        "full_rotations": 1,
        "rotations": [
            {
                "support_foot": "right",
                "axis": "vertical",
                "brake": "land low and hold",
            }
        ],
    }


def _valid_camera() -> dict:
    return {
        "placement": "three metres in front of the dancer",
        "height": "chest height",
        "optical_axis": "level, aimed at the dancer",
        "spatial_relation": "the dancer fills the middle of the frame",
        "physical_result": "the full body stays visible",
        "movement_response": "the camera tracks in as the dancer advances",
        "camera_lock": "the camera stops when the dancer stops",
        "distance_m": 3.0,
        "preset": "none",
    }


def _valid_sync() -> dict:
    return {
        "shots": [
            {
                "action_start_s": 0.0,
                "action_peak_s": 1.0,
                "action_end_s": 2.0,
                "camera_start_s": 0.0,
                "camera_peak_s": 1.0,
                "camera_settled_s": 1.5,
                "hero": True,
                "framing_before_action": True,
            }
        ],
    }


def _valid_transitions() -> dict:
    return {
        "boundaries": [
            {
                "from_segment": "segment_1",
                "to_segment": "segment_2",
                "mechanism": "match_on_action",
                "hook": "the arm sweep continues across the cut",
            }
        ],
        "climax": {
            "mechanism": "hard_cut_on_beat",
            "trigger": "the drum drop at the chorus",
        },
        "ending": {"design": "the dancer freezes in a wide shot"},
    }


def _valid_prompt() -> dict:
    return {
        "sections": {
            "subject_definitions": "One dancer in a red dress, as defined.",
            "summary": "A dancer performs a short routine in a studio.",
            "retention_analysis": "The red dress stays unchanged throughout.",
            "detailed_description": "The dancer steps forward and turns; no dialogue.",
            "overall_soundscape": "The supplied music plays throughout.",
            "non_diegetic_music": "The supplied music is the only music.",
        },
        "audio": {"source": "audio_1", "unchanged": True},
        "timecode_basis": "global",
        "shots": [
            {
                "basis": "global",
                "start_s": 0.52,
                "end_s": 8.52,
                "description": "The dancer steps forward and turns.",
            }
        ],
        "dance_only": True,
    }


def _valid_review() -> dict:
    return {
        "preflight": {
            "items": dict.fromkeys(
                (
                    "music",
                    "reference",
                    "person",
                    "environment",
                    "props",
                    "genre",
                    "chain",
                    "capacity",
                    "footwork",
                    "camera_physical",
                    "camera_sync",
                    "edit_reason",
                    "self_contained",
                    "language",
                    "sound",
                    "mechanical",
                ),
                True,
            )
        },
        "post_scores": {
            "person_consistency": 4,
            "scene_consistency": 4,
            "rhythm_sync": 4,
            "action_completeness": 4,
            "dynamics_credibility": 4,
            "genre_style": 4,
            "camera_quality": 4,
            "shot_readability": 4,
            "transition_value": 4,
            "commercial_feel": 3,
        },
        "diagnosis": {
            "layer": "timing",
            "cause": "the jump lands half a beat late",
        },
        "fixes": [
            {
                "symptom": "jump lands late",
                "check": "beat grid against the landing frame",
                "fix": "shift the jump one beat earlier",
            }
        ],
        "overall": "pass",
    }


def _valid_pack() -> dict:
    return {
        "title": "Morning Trouble",
        "revision": "rev 1.0",
        "sections": [
            "revision_history",
            "overall_direction",
            "picture_responsibilities",
            "visual_bible",
            "audio_index",
            "h3_prompts",
            "transition_map",
            "preflight_checklist",
            "post_review",
        ],
        "segments": [
            {
                "id": "segment_1",
                "global_start": "00:00.520",
                "global_end": "00:08.520",
                "local_duration_s": 8.0,
                "audio_file": "audio_1.mp3",
                "h3_prompt": {
                    "sections": {
                        "subject_definitions": "One dancer in a red dress.",
                        "summary": "A dancer performs a short routine.",
                        "retention_analysis": "The red dress stays unchanged.",
                        "detailed_description": "The dancer steps forward.",
                        "overall_soundscape": "The supplied music plays.",
                        "non_diegetic_music": "The supplied music only.",
                    },
                    "internal": {
                        "subject_definitions": "One dancer in a red dress.",
                        "reference_roles": "Picture 1 identity.",
                        "global_continuity": "The dress stays red.",
                        "music_rules": "The supplied audio is unchanged.",
                        "directing_concept": "A short studio routine.",
                        "action_camera_timeline": "Step forward, then turn.",
                        "end_state": "Settle into a low stance.",
                        "overall_soundscape": "The supplied music plays.",
                        "non_diegetic_music": "The supplied music only.",
                    },
                },
            },
            {
                "id": "segment_2",
                "global_start": "00:08.520",
                "global_end": "00:16.520",
                "local_duration_s": 8.0,
                "audio_file": "audio_1.mp3",
                "h3_prompt": {
                    "sections": {
                        "subject_definitions": "One dancer in a red dress.",
                        "summary": "The dancer continues the routine.",
                        "retention_analysis": "The red dress stays unchanged.",
                        "detailed_description": "The dancer jumps and lands.",
                        "overall_soundscape": "The supplied music plays.",
                        "non_diegetic_music": "The supplied music only.",
                    },
                    "internal": {
                        "subject_definitions": "One dancer in a red dress.",
                        "reference_roles": "Picture 1 identity.",
                        "global_continuity": "The dress stays red.",
                        "music_rules": "The supplied audio is unchanged.",
                        "directing_concept": "A short studio routine.",
                        "action_camera_timeline": "Jump and land.",
                        "end_state": "Hold the final pose.",
                        "overall_soundscape": "The supplied music plays.",
                        "non_diegetic_music": "The supplied music only.",
                    },
                },
            },
        ],
        "transitions": [
            {
                "from_segment": "segment_1",
                "to_segment": "segment_2",
                "mechanism": "match_on_action",
            }
        ],
    }


def test_music_structure_pass():
    assert check_dance_music_structure(_valid_music())["verdict"] == "pass"


def test_music_structure_rejects_bad_beat():
    bad = _valid_music()
    bad["beat_s"] = 0.9
    result = check_dance_music_structure(bad)
    assert result["verdict"] == "fail"
    assert result["issues"][0]["code"] == "beat_mismatch"


def test_music_structure_rejects_mixed_timecodes():
    bad = _valid_music()
    bad["shots"][0]["basis"] = "local"
    result = check_dance_music_structure(bad)
    assert result["verdict"] == "fail"
    assert result["issues"][0]["code"] == "timecode_mixed"


def test_reference_roles_pass():
    assert check_dance_reference_roles(_valid_reference())["verdict"] == "pass"


def test_reference_roles_rejects_wrong_priority():
    bad = _valid_reference()
    bad["priority"]["identity_source"] = "picture_2"
    result = check_dance_reference_roles(bad)
    assert result["verdict"] == "fail"
    assert result["issues"][0]["code"] == "priority_identity_wrong"


def test_reference_roles_rejects_wrong_roles():
    bad = _valid_reference()
    bad["template"] = "three_classical"
    result = check_dance_reference_roles(bad)
    assert result["verdict"] == "fail"
    assert result["issues"][0]["code"] == "role_mismatch"


def test_asset_prop_ledger_pass():
    assert check_dance_asset_prop_ledger(_valid_assets())["verdict"] == "pass"


def test_asset_prop_ledger_rejects_h3_added_prop():
    bad = _valid_assets()
    bad["added_props"] = ["red lantern"]
    result = check_dance_asset_prop_ledger(bad)
    assert result["verdict"] == "fail"
    assert result["issues"][0]["code"] == "prop_added_undeclared"


def test_asset_prop_ledger_rejects_zero_quantity():
    bad = _valid_assets()
    bad["props"][0]["quantity"] = 0
    result = check_dance_asset_prop_ledger(bad)
    assert result["verdict"] == "fail"
    assert result["issues"][0]["code"] == "prop_quantity_invalid"


def test_genre_grammar_pass():
    assert check_dance_genre_grammar(_valid_genre())["verdict"] == "pass"


def test_genre_grammar_rejects_unknown_genre():
    bad = _valid_genre()
    bad["primary_genre"] = "tango"
    result = check_dance_genre_grammar(bad)
    assert result["verdict"] == "fail"
    assert result["issues"][0]["code"] == "primary_genre_unknown"


def test_genre_grammar_rejects_undeclared_move():
    bad = _valid_genre()
    bad["moves"][0]["genre"] = "ballet"
    result = check_dance_genre_grammar(bad)
    assert result["verdict"] == "fail"
    assert result["issues"][0]["code"] == "move_genre_undeclared"


def test_action_chain_pass():
    assert check_dance_action_chain(_valid_chain())["verdict"] == "pass"


def test_action_chain_rejects_library_code():
    bad = _valid_chain()
    bad["layers"]["main_chain"]["peak"] = "C16"
    result = check_dance_action_chain(bad)
    assert result["verdict"] == "fail"
    assert result["issues"][0]["code"] == "library_code_refused"


def test_action_chain_rejects_wrong_step_count():
    bad = _valid_chain()
    bad["steps"] = bad["steps"][:4]
    result = check_dance_action_chain(bad)
    assert result["verdict"] == "fail"
    assert result["issues"][0]["code"] == "steps_incomplete"


def test_time_window_pass():
    assert check_dance_time_window(_valid_time())["verdict"] == "pass"


def test_time_window_rejects_short_window():
    bad = _valid_time()
    bad["windows"][0]["duration_s"] = 0.2
    result = check_dance_time_window(bad)
    assert result["verdict"] == "fail"
    assert result["issues"][0]["code"] == "window_too_short"


def test_time_window_rejects_too_many_turns():
    bad = _valid_time()
    bad["full_rotations"] = 3
    bad["rotations"] = [
        {"support_foot": "right", "axis": "vertical", "brake": "land low"} for _ in range(3)
    ]
    result = check_dance_time_window(bad)
    assert result["verdict"] == "fail"
    assert result["issues"][0]["code"] == "rotations_over_budget"


def test_camera_physical_pass():
    assert check_dance_camera_physical(_valid_camera())["verdict"] == "pass"


def test_camera_physical_rejects_degree_law():
    bad = _valid_camera()
    bad["angle_degrees"] = 45.0
    result = check_dance_camera_physical(bad)
    assert result["verdict"] == "fail"
    assert result["issues"][0]["code"] == "angle_number_refused"


def test_camera_physical_rejects_abstract_term():
    bad = _valid_camera()
    bad["movement_response"] = "a dutch angle sweep follows the dancer"
    result = check_dance_camera_physical(bad)
    assert result["verdict"] == "fail"
    assert result["issues"][0]["code"] == "abstract_angle_term"


def test_camera_sync_pass():
    assert check_dance_camera_sync(_valid_sync())["verdict"] == "pass"


def test_camera_sync_rejects_late_framing():
    bad = _valid_sync()
    bad["shots"][0]["framing_before_action"] = False
    result = check_dance_camera_sync(bad)
    assert result["verdict"] == "fail"
    assert result["issues"][0]["code"] == "hero_framing_late"


def test_camera_sync_rejects_late_camera_start():
    bad = _valid_sync()
    bad["shots"][0]["camera_start_s"] = 0.2
    result = check_dance_camera_sync(bad)
    assert result["verdict"] == "fail"
    assert result["issues"][0]["code"] == "camera_late_start"


def test_transition_gate_pass():
    assert check_dance_transitions(_valid_transitions())["verdict"] == "pass"


def test_transition_gate_rejects_multiple_mechanisms():
    bad = _valid_transitions()
    bad["boundaries"][0]["mechanism"] = ["match_on_action", "hard_cut_on_beat"]
    result = check_dance_transitions(bad)
    assert result["verdict"] == "fail"
    assert result["issues"][0]["code"] == "mechanism_not_single"


def test_transition_gate_rejects_overused_dissolve():
    bad = _valid_transitions()
    bad["boundaries"] = [
        {
            "from_segment": f"segment_{i}",
            "to_segment": f"segment_{i + 1}",
            "mechanism": "soft_dissolve",
            "hook": "the light fades",
        }
        for i in range(1, 4)
    ]
    result = check_dance_transitions(bad)
    assert result["verdict"] == "fail"
    assert result["issues"][0]["code"] == "dissolve_overused"


def test_h3_prompt_gate_pass():
    assert check_dance_h3_prompt(_valid_prompt())["verdict"] == "pass"


def test_h3_prompt_gate_rejects_extra_section():
    bad = _valid_prompt()
    bad["sections"]["integrated_multimodal_description"] = "A summary."
    result = check_dance_h3_prompt(bad)
    assert result["verdict"] == "fail"
    assert result["issues"][0]["code"] == "sections_not_six"


def test_h3_prompt_gate_rejects_cross_reference():
    bad = _valid_prompt()
    bad["sections"]["summary"] = "Same as above."
    result = check_dance_h3_prompt(bad)
    assert result["verdict"] == "fail"
    assert result["issues"][0]["code"] == "cross_reference"


def test_generation_review_gate_pass():
    assert check_dance_generation_review(_valid_review())["verdict"] == "pass"


def test_generation_review_gate_rejects_incomplete_preflight():
    bad = _valid_review()
    bad["preflight"]["items"]["music"] = False
    result = check_dance_generation_review(bad)
    assert result["verdict"] == "fail"
    assert result["issues"][0]["code"] == "preflight_incomplete"


def test_generation_review_gate_rejects_score_out_of_range():
    bad = _valid_review()
    bad["post_scores"]["rhythm_sync"] = 6
    result = check_dance_generation_review(bad)
    assert result["verdict"] == "fail"
    assert result["issues"][0]["code"] == "score_out_of_range"


def test_pack_format_gate_pass():
    assert check_dance_mv_pack(_valid_pack())["verdict"] == "pass"


def test_pack_format_gate_rejects_wrong_sections():
    bad = _valid_pack()
    bad["sections"] = bad["sections"][::-1]
    result = check_dance_mv_pack(bad)
    assert result["verdict"] == "fail"
    assert result["issues"][0]["code"] == "format_sections_wrong"


def test_pack_format_gate_rejects_missing_transition():
    bad = _valid_pack()
    bad["transitions"] = []
    result = check_dance_mv_pack(bad)
    assert result["verdict"] == "fail"
    assert result["issues"][0]["code"] == "transition_count_mismatch"


def _valid_segment_card() -> dict:
    return {
        "segment_id": "segment_1",
        "title": "Opening",
        "duration_s": 8.0,
        "global_start_s": 0.52,
        "audio_file": "audio_1.mp3",
        "music": {"bpm": 120.0, "bar_length_s": 2.0},
        "camera_in": "wide front",
        "camera_out": "medium front",
        "transition_in": "hard_cut_on_beat",
        "transition_out": "match_on_action",
        "key_poses": ["arms wide open"],
        "must_land_actions": ["jump land"],
        "end_state": {"support_foot": "both", "direction": "down"},
    }


def test_segment_card_schema_valid_compiles():
    contract = compile_dance_segment_card(_valid_segment_card())
    assert contract["executed_here"] is False
    assert contract["output_file"] is None
    assert contract["segment_id"] == "segment_1"


def test_segment_card_schema_missing_field():
    bad = _valid_segment_card()
    del bad["title"]
    with pytest.raises(CapabilityError) as excinfo:
        compile_dance_segment_card(bad)
    assert "title" in str(excinfo.value)


def _valid_action_chain_schema() -> dict:
    return {
        "chain_id": "chain_1",
        "segment_id": "segment_1",
        "groove": ["bounce on the beat"],
        "main_chain": ["step turn", "arm sweep"],
        "micro_expressions": ["smile"],
        "steps": [
            {
                "order": i + 1,
                "action": f"step {i + 1}",
                "duration_s": 0.5,
            }
            for i in range(5)
        ],
        "entry_state": {"support_foot": "left", "direction": "forward"},
        "exit_state": {"support_foot": "both", "direction": "down"},
    }


def test_action_chain_schema_valid_compiles():
    contract = compile_dance_action_chain(_valid_action_chain_schema())
    assert contract["executed_here"] is False
    assert contract["output_file"] is None
    assert contract["chain_id"] == "chain_1"


def test_action_chain_schema_rejects_library_code():
    bad = _valid_action_chain_schema()
    bad["main_chain"] = ["step turn", "C16"]
    with pytest.raises(CapabilityError) as excinfo:
        compile_dance_action_chain(bad)
    assert "library code" in str(excinfo.value)


def _valid_camera_shot() -> dict:
    return {
        "shot_id": "shot_1",
        "segment_id": "segment_1",
        "start_s": 0.0,
        "end_s": 2.0,
        "distance_m": 3.0,
        "height": "chest height",
        "position": "front",
        "motion": "track in",
        "move_distance_m": 1.0,
        "move_duration_s": 1.0,
        "framing_before_hero": True,
        "settle_s": 1.0,
    }


def test_camera_shot_schema_valid_compiles():
    contract = compile_dance_camera_shot(_valid_camera_shot())
    assert contract["executed_here"] is False
    assert contract["output_file"] is None
    assert contract["shot_id"] == "shot_1"


def test_camera_shot_schema_rejects_reversed_time():
    bad = _valid_camera_shot()
    bad["end_s"] = 0.0
    with pytest.raises(CapabilityError) as excinfo:
        compile_dance_camera_shot(bad)
    assert "end_s" in str(excinfo.value)


def _valid_transition_table() -> dict:
    return {
        "table_id": "table_1",
        "film_id": "film_1",
        "entries": [
            {
                "from_segment": "segment_1",
                "to_segment": "segment_2",
                "mechanism": "match_on_action",
                "hook": "the arm sweep continues",
            }
        ],
    }


def test_transition_table_schema_valid_compiles():
    contract = compile_dance_transition_table(_valid_transition_table())
    assert contract["executed_here"] is False
    assert contract["output_file"] is None
    assert contract["table_id"] == "table_1"


def test_transition_table_schema_rejects_unknown_mechanism():
    bad = _valid_transition_table()
    bad["entries"][0]["mechanism"] = "zoom burst"
    with pytest.raises(CapabilityError) as excinfo:
        compile_dance_transition_table(bad)
    assert "unknown mechanism" in str(excinfo.value)


def _valid_prompt_pack() -> dict:
    return {
        "pack_id": "pack_1",
        "title": "Morning Trouble",
        "revision": "rev 1.0",
        "sections": [
            "revision_history",
            "overall_direction",
            "picture_responsibilities",
            "visual_bible",
            "audio_index",
            "h3_prompts",
            "transition_map",
            "preflight_checklist",
            "post_review",
        ],
        "segments": [
            {
                "id": "segment_1",
                "global_start": "00:00.520",
                "global_end": "00:08.520",
                "local_duration_s": 8.0,
                "audio_file": "audio_1.mp3",
                "h3_prompt": {},
            },
            {
                "id": "segment_2",
                "global_start": "00:08.520",
                "global_end": "00:16.520",
                "local_duration_s": 8.0,
                "audio_file": "audio_1.mp3",
                "h3_prompt": {},
            },
        ],
        "transitions": [
            {
                "from_segment": "segment_1",
                "to_segment": "segment_2",
                "mechanism": "match_on_action",
            }
        ],
    }


def test_prompt_pack_schema_valid_compiles():
    contract = compile_dance_mv_prompt_pack(_valid_prompt_pack())
    assert contract["executed_here"] is False
    assert contract["output_file"] is None
    assert contract["pack_id"] == "pack_1"


def test_prompt_pack_schema_rejects_wrong_transition_count():
    bad = _valid_prompt_pack()
    bad["transitions"] = []
    with pytest.raises(CapabilityError) as excinfo:
        compile_dance_mv_prompt_pack(bad)
    assert "transition count" in str(excinfo.value)


EXPECTED_DANCE_NAMES = {
    "qa.dance_music_structure_gate",
    "qa.dance_reference_role_gate",
    "qa.dance_asset_prop_ledger_gate",
    "qa.dance_genre_grammar_gate",
    "qa.dance_action_chain_gate",
    "qa.dance_time_window_gate",
    "qa.dance_camera_physical_gate",
    "qa.dance_camera_sync_gate",
    "qa.dance_transition_gate",
    "qa.dance_h3_prompt_gate",
    "qa.dance_generation_review_gate",
    "qa.dance_mv_pack_format_gate",
    "video.dance_segment_card_schema",
    "video.dance_action_chain_schema",
    "video.dance_camera_shot_schema",
    "video.dance_transition_table_schema",
    "video.dance_mv_prompt_pack_schema",
}


def test_dance_graft_registered_once():
    from hevi.capabilities import list_capabilities

    found = [c.name for c in list_capabilities() if c.name in EXPECTED_DANCE_NAMES]
    assert sorted(found) == sorted(EXPECTED_DANCE_NAMES)
    assert len(found) == 17
