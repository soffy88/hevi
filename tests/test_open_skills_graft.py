"""Tests for the 20 open-skills graft (A1-A6 gates + B1/B2 fake contracts).

Every gate/contract gets a positive case and at least one
negative case. Nothing here renders, installs, or executes any
of the 20 upstream items.
"""

from __future__ import annotations

import pytest

from hevi.capabilities.animejs_v4_vocabulary import (
    V4_EASINGS,
    V4_ENTRY_POINTS,
    check_animejs_v4_plan,
)
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.lottie_overlay_adapter import (
    compile_lottie_overlay_contract,
)
from hevi.capabilities.motion_variant_gate import check_motion_variant
from hevi.capabilities.open_skills_method_notes import (
    check_method_note,
    method_notes,
)
from hevi.capabilities.postprocessing_variant_gate import (
    check_postprocessing_variant,
)
from hevi.capabilities.quarks_particle_contract import (
    compile_quarks_particle_contract,
)
from hevi.capabilities.remotion_skills_method_gate import (
    PINNED_SKILLS_COMMIT,
    check_remotion_skills_method,
)
from hevi.capabilities.whisperx_subtitle_contract import (
    check_whisperx_subtitle_contract,
)


def _good_composition(**overrides):
    comp = {
        "id": "main",
        "fps": 30,
        "width": 1920,
        "height": 1080,
        "durationInFrames": 900,
        "duration_seconds": 30,
        "captions_declared": True,
        "render_verified": False,
    }
    comp.update(overrides)
    return comp


# --- A1: Remotion Skills method gate -------------------------------------


def test_a1_passes_clean_plan():
    report = check_remotion_skills_method(
        {
            "follows_remotion_skills": True,
            "skills_commit": PINNED_SKILLS_COMMIT,
            "compositions": [_good_composition()],
        }
    )
    assert report["verdict"] == "pass"
    assert report["render_verified_by_this_gate"] is False
    assert report["pinned_commit"] == PINNED_SKILLS_COMMIT


def test_a1_frame_time_mismatch_fails():
    report = check_remotion_skills_method(
        {"compositions": [_good_composition(durationInFrames=901)]}
    )
    assert report["verdict"] == "fail"
    assert any(i["code"].endswith("frame_time_mismatch") for i in report["issues"])


def test_a1_wrong_commit_fails():
    report = check_remotion_skills_method(
        {
            "follows_remotion_skills": True,
            "skills_commit": "deadbeef",
            "compositions": [_good_composition()],
        }
    )
    assert report["verdict"] == "fail"
    assert any(i["code"] == "skills_commit_mismatch" for i in report["issues"])


def test_a1_render_claim_without_evidence_fails():
    report = check_remotion_skills_method(
        {
            "compositions": [
                _good_composition(render_verified=True, render_evidence="")
            ]
        }
    )
    assert report["verdict"] == "fail"
    assert any(
        i["code"].endswith("render_claim_without_evidence")
        for i in report["issues"]
    )


def test_a1_render_claim_with_evidence_passes_but_gate_verifies_nothing():
    report = check_remotion_skills_method(
        {
            "compositions": [
                _good_composition(
                    render_verified=True, render_evidence="runbook run #7 log"
                )
            ]
        }
    )
    assert report["verdict"] == "pass"
    assert report["render_verified_by_this_gate"] is False


def test_a1_captions_required_but_undeclared_fails():
    report = check_remotion_skills_method(
        {
            "captions_required": True,
            "compositions": [_good_composition(captions_declared=False)],
        }
    )
    assert report["verdict"] == "fail"
    assert any(i["code"].endswith("captions_undeclared") for i in report["issues"])


def test_a1_non_object_plan_fails():
    assert check_remotion_skills_method("nope")["verdict"] == "fail"


# --- A2: Anime.js v4 vocabulary -------------------------------------------


def test_a2_vocabulary_counts():
    assert len(V4_ENTRY_POINTS) == 9
    assert len(V4_EASINGS) == 44
    assert "createTimeline" in V4_ENTRY_POINTS
    assert "outQuad" in V4_EASINGS
    assert "inOutExpo" in V4_EASINGS
    assert "linear" in V4_EASINGS


def test_a2_passes_v4_plan():
    report = check_animejs_v4_plan(
        {
            "version": "4.5.0",
            "animations": [
                {
                    "entry_point": "createTimeline",
                    "easing": "outElastic(1, .5)",
                    "code_snippet": "animate('.box', {x: 100})",
                }
            ],
        }
    )
    assert report["verdict"] == "pass"


def test_a2_v3_entry_point_fails():
    report = check_animejs_v4_plan(
        {"animations": [{"entry_point": "anime", "easing": "linear"}]}
    )
    assert report["verdict"] == "fail"


def test_a2_v3_easing_spelling_fails():
    report = check_animejs_v4_plan(
        {"animations": [{"entry_point": "animate", "easing": "easeOutQuad"}]}
    )
    assert report["verdict"] == "fail"
    assert any(i["code"].endswith("unknown_easing") for i in report["issues"])


def test_a2_v3_version_and_marker_fail():
    report = check_animejs_v4_plan(
        {
            "version": "3.2.2",
            "animations": [
                {
                    "entry_point": "animate",
                    "code_snippet": "anime.timeline({})",
                }
            ],
        }
    )
    assert report["verdict"] == "fail"
    codes = [i["code"] for i in report["issues"]]
    assert "v3_version" in codes
    assert any(c.endswith("v3_api_marker") for c in codes)


# --- A3: Motion variant gate ----------------------------------------------


def test_a3_passes_both_variants():
    report = check_motion_variant(
        {
            "usages": [
                {"import_source": "motion/react", "api_kind": "component"},
                {"import_source": "motion/react", "api_kind": "hook"},
                {"import_source": "motion/dom", "api_kind": "standalone"},
            ]
        }
    )
    assert report["verdict"] == "pass"


def test_a3_bare_import_fails():
    for source in ("motion", "framer-motion"):
        report = check_motion_variant(
            {"usages": [{"import_source": source, "api_kind": "component"}]}
        )
        assert report["verdict"] == "fail"


def test_a3_mismatch_fails():
    report = check_motion_variant(
        {"usages": [{"import_source": "motion/dom", "api_kind": "hook"}]}
    )
    assert report["verdict"] == "fail"
    assert any(i["code"].endswith("variant_api_mismatch") for i in report["issues"])
    report = check_motion_variant(
        {"usages": [{"import_source": "motion/react", "api_kind": "standalone"}]}
    )
    assert report["verdict"] == "fail"


# --- A4: postprocessing variant gate --------------------------------------


def test_a4_passes_both_variants():
    report = check_postprocessing_variant(
        {
            "passes": [
                {
                    "variant": "pmndrs",
                    "pass_name": "Bloom",
                    "import_path": "postprocessing",
                },
                {
                    "variant": "three-jsm",
                    "pass_name": "UnrealBloom",
                    "import_path": "three/addons/postprocessing/UnrealBloomPass.js",
                },
                {
                    "variant": "three-jsm",
                    "pass_name": "Output",
                    "import_path": "./vendor/three/postprocessing/OutputPass.js",
                },
            ]
        }
    )
    assert report["verdict"] == "pass"


def test_a4_mixed_paths_fail():
    report = check_postprocessing_variant(
        {
            "passes": [
                {
                    "variant": "pmndrs",
                    "pass_name": "Bloom",
                    "import_path": "three/addons/postprocessing/EffectComposer.js",
                }
            ]
        }
    )
    assert report["verdict"] == "fail"
    report = check_postprocessing_variant(
        {
            "passes": [
                {
                    "variant": "three-jsm",
                    "pass_name": "Bloom",
                    "import_path": "postprocessing",
                }
            ]
        }
    )
    assert report["verdict"] == "fail"


def test_a4_undeclared_variant_fails():
    report = check_postprocessing_variant(
        {
            "passes": [
                {"variant": "three", "pass_name": "X", "import_path": "postprocessing"}
            ]
        }
    )
    assert report["verdict"] == "fail"


# --- A5: WhisperX subtitle contract ---------------------------------------


def _good_subtitle_plan(**overrides):
    plan = {
        "asr_engine": "whisperx",
        "execution_status": "contract_only",
        "segments": [
            {
                "start": 0.0,
                "end": 2.0,
                "words": [
                    {"word": "hello", "start": 0.0, "end": 0.5},
                    {"word": "world", "start": 0.5, "end": 1.0},
                ],
            }
        ],
    }
    plan.update(overrides)
    return plan


def test_a5_passes_word_level_plan():
    report = check_whisperx_subtitle_contract(_good_subtitle_plan())
    assert report["verdict"] == "pass"
    assert report["whisperx_executed_here"] is False
    assert report["live_asr_engine"] == "faster-whisper"


def test_a5_word_outside_segment_fails():
    plan = _good_subtitle_plan()
    plan["segments"][0]["words"][1]["end"] = 3.0
    report = check_whisperx_subtitle_contract(plan)
    assert report["verdict"] == "fail"
    assert any(i["code"].endswith("outside_segment") for i in report["issues"])


def test_a5_out_of_order_words_fail():
    plan = _good_subtitle_plan()
    plan["segments"][0]["words"] = [
        {"word": "b", "start": 0.5, "end": 1.0},
        {"word": "a", "start": 0.0, "end": 0.5},
    ]
    assert check_whisperx_subtitle_contract(plan)["verdict"] == "fail"


def test_a5_multi_speaker_without_diarization_fails():
    plan = _good_subtitle_plan(speakers=["A", "B"])
    assert check_whisperx_subtitle_contract(plan)["verdict"] == "fail"
    plan = _good_subtitle_plan(
        speakers=["A", "B"], diarization_declared=True
    )
    assert check_whisperx_subtitle_contract(plan)["verdict"] == "pass"


def test_a5_executed_claim_fails():
    plan = _good_subtitle_plan(execution_status="executed_here")
    report = check_whisperx_subtitle_contract(plan)
    assert report["verdict"] == "fail"
    assert any(
        i["code"] == "execution_status_invalid" for i in report["issues"]
    )


def test_a5_unknown_engine_fails():
    plan = _good_subtitle_plan(asr_engine="whisper")
    assert check_whisperx_subtitle_contract(plan)["verdict"] == "fail"


# --- A6: method notes ------------------------------------------------------


def test_a6_table_has_twenty_items():
    notes = method_notes()
    assert len(notes) == 20
    assert [n["index"] for n in notes] == [f"{i:02d}" for i in range(1, 21)]
    assert notes[1]["license"] == "undeclared"  # Remotion Skills
    assert notes[13]["license"] == "GPL-3.0"  # ComfyUI
    assert notes[0]["license"].startswith("per in-repo LICENSE text")


def test_a6_license_mismatch_fails():
    report = check_method_note({"item": 14, "license_claim": "MIT"})
    assert report["verdict"] == "fail"
    assert any(i["code"] == "license_mismatch" for i in report["issues"])


def test_a6_unknown_item_fails():
    assert check_method_note({"item": "NoSuchTool"})["verdict"] == "fail"
    assert check_method_note({"item": 21})["verdict"] == "fail"


def test_a6_unverified_effect_claim_fails():
    report = check_method_note({"item": 9, "effect_verified": True})
    assert report["verdict"] == "fail"
    assert any(i["code"] == "effect_unverified" for i in report["issues"])


def test_a6_installed_claim_for_method_only_fails():
    report = check_method_note({"item": 2, "installed": True})
    assert report["verdict"] == "fail"
    report = check_method_note({"item": "FFmpeg"})
    assert report["verdict"] == "pass"


# --- B1: Lottie overlay adapter (fake) -------------------------------------


def _good_lottie_plan(**overrides):
    plan = {
        "fps": 30,
        "width": 1080,
        "height": 1920,
        "overlays": [
            {
                "id": "badge",
                "source_kind": "lottie_json",
                "source_ref": "assets/badge.json",
                "start_frame": 0,
                "end_frame": 90,
                "loop": True,
                "transparent": True,
            }
        ],
    }
    plan.update(overrides)
    return plan


def test_b1_compiles_contract_and_executes_nothing():
    contract = compile_lottie_overlay_contract(_good_lottie_plan())
    assert contract["executed_here"] is False
    assert contract["rendered_here"] is False
    assert contract["output_file"] is None
    assert contract["player"]["bundled_here"] is False
    assert contract["overlays"][0]["layer"] == "lottie_overlay"


def test_b1_opaque_overlay_fails():
    plan = _good_lottie_plan()
    plan["overlays"][0]["transparent"] = False
    with pytest.raises(CapabilityError):
        compile_lottie_overlay_contract(plan)


def test_b1_bad_bounds_and_source_fail():
    plan = _good_lottie_plan()
    plan["overlays"][0]["end_frame"] = 0
    with pytest.raises(CapabilityError):
        compile_lottie_overlay_contract(plan)
    plan = _good_lottie_plan()
    plan["overlays"][0]["source_kind"] = "mp4"
    with pytest.raises(CapabilityError):
        compile_lottie_overlay_contract(plan)


# --- B2: three.quarks particle contract (fake) -----------------------------


def _good_quarks_plan(**overrides):
    plan = {
        "library_version": "1.0.0-pinned",
        "gpu_required": True,
        "emitters": [
            {
                "id": "sparks",
                "emission_rate_per_second": 120,
                "lifetime_seconds": 1.5,
                "behavior": "rise-and-fade",
            }
        ],
    }
    plan.update(overrides)
    return plan


def test_b2_compiles_contract_and_executes_nothing():
    contract = compile_quarks_particle_contract(_good_quarks_plan())
    assert contract["executed_here"] is False
    assert contract["rendered_here"] is False
    assert contract["output_file"] is None
    assert contract["gpu_required"] is True
    assert contract["library"]["installed_here"] is False


def test_b2_missing_version_pin_fails():
    plan = _good_quarks_plan()
    del plan["library_version"]
    with pytest.raises(CapabilityError):
        compile_quarks_particle_contract(plan)


def test_b2_gpu_acknowledgement_missing_fails():
    plan = _good_quarks_plan(gpu_required=False)
    with pytest.raises(CapabilityError):
        compile_quarks_particle_contract(plan)


def test_b2_bad_emitter_fails():
    plan = _good_quarks_plan()
    plan["emitters"][0]["emission_rate_per_second"] = 0
    with pytest.raises(CapabilityError):
        compile_quarks_particle_contract(plan)
